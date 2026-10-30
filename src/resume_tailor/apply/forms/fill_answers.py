"""Uploads, long-text answers and leftover-field resolution within one wizard step."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from resume_tailor.apply.answers import (
    answer,
    answer_memory,
    education,
    form_facts,
    model_fallback,
    widget_actions,
)
from resume_tailor.apply.forms import form_guards, form_routes
from resume_tailor.apply.funnel import cover_on_demand

from . import fill_buttons, fill_outcomes, fill_page, fill_state, fill_widgets, upload_replace

#: Review notes that carry their reason, so an observed value never clears them.
SHORTENED_NOTE = "shortened to fit the form's limit"
NOT_DRAFTED_NOTE = "could not draft an answer"

_log = logging.getLogger(__name__)

#: Extra fill passes a step gets when its questions change after answers.
_MAX_RESCANS = 2
#: Answers others depend on go first: Country sets the address lists, and a postal-code
#: lookup fills City, County and State (Oracle Recruiting, 2026-10).
_FIRST_KEYS = ("country", "postal_code")


@contextlib.contextmanager
def _app_upload(target: Any):
    """Mark the app's own upload in the frame, so the tab's listener does not record it
    as a file the applicant attached (`answer_harvest`)."""
    from resume_tailor.apply.funnel import answer_harvest  # noqa: PLC0415

    with contextlib.suppress(Exception):
        target.evaluate(answer_harvest.APP_UPLOAD_JS, True)
    try:
        yield
    finally:
        with contextlib.suppress(Exception):
            target.evaluate(answer_harvest.APP_UPLOAD_JS, False)


def _dependency_order(item: Any) -> int:
    key = item.get("key") if isinstance(item, dict) else None
    return _FIRST_KEYS.index(key) if key in _FIRST_KEYS else len(_FIRST_KEYS)


def _asked(label: str, help_text: str) -> str:
    """What a written answer is drafted for: the label, then the helper text the form
    shows under it, which can list what the answer must cover (Twitch's "Describe: the
    context/problem, what you built, ..." was never drafted from, 2026-10)."""
    help_text = " ".join(help_text.split())
    if not help_text or help_text.casefold() in " ".join(label.split()).casefold():
        return label
    return f"{label}\n{help_text}"


class _FillAnswers(fill_state._FillState):
    """`_FillRun` steps that attach files and answer what `filler.js` left blank."""

    def _upload_attachments(self) -> None:
        """File uploads via Playwright (cannot set from page JS)."""
        resume_uploaded = False
        for fin in self._file_inputs():
            if self._out_of_time():
                self.needs_review.append("Fill stopped before all attachments were checked")
                break
            resume_uploaded |= self._upload_one(fin)
        if resume_uploaded:
            fixes = fill_widgets._correct_resume_prefill(
                self.page, self.frames, self.filler_js, self.fields, self.hints
            )
            for item in fixes:
                if item.get("corrected"):
                    self.merged["filled"].append(item)
                    fixed = item.get("label") or "a field"
                    self.progress(f"corrected {fixed} after the resume upload")
                else:
                    self.merged["leftovers"].append(item)
            self._refill_emptied()

    def _refill_emptied(self) -> None:
        """Fill again what the resume upload emptied. Paylocity's "Fill out application
        with my resume" redraws the form blank after the upload (2026-10), and the
        correction pass rewrites only boxes that still hold a value. ``filler.js`` keeps
        every box that has one, so only the emptied ones are typed into again."""
        known = {
            (item.get("frame_index", 0), item.get("selector"))
            for item in self.merged["filled"] if isinstance(item, dict)
        }
        refilled = 0
        for frame_index, frame in enumerate(self._sync_frames()):
            try:
                again = fill_widgets._fill_frame(
                    frame, self.filler_js, self.fields, self.hints, self.facts,
                    self.classify_unkeyed, self.classify_notices,
                )
            except Exception as exc:  # noqa: BLE001 - cross-origin frames fail evaluate
                _log.debug("refill after upload skipped frame %d: %s", frame_index, exc)
                continue
            for item in (again or {}).get("filled") or []:
                if not isinstance(item, dict) or item.get("preserved"):
                    continue
                identity = (frame_index, item.get("selector"))
                refilled += identity in known
                if identity not in known:
                    self.merged["filled"].append({**item, "frame_index": frame_index})
                    known.add(identity)
        if refilled:
            self.progress(f"filled {refilled} answer(s) again after the resume upload cleared them")

    def _file_inputs(self) -> list[Any]:
        """The scanned file inputs plus a resume/cover input found by selector if the scan
        did not register one."""
        page = self.page
        file_inputs = list(self.merged.get("file_inputs") or [])
        existing_sels = {f.get("selector") for f in file_inputs if isinstance(f, dict)}
        for fin_sel in (
            "input[type='file']#resume",
            "input[type='file'][id*='resume' i]",
            "input[type='file'][name*='resume' i]",
        ):
            if fin_sel not in existing_sels and fill_buttons._locator_exists(page.locator(fin_sel)):
                file_inputs.insert(0, {"selector": fin_sel, "label": "Resume"})
                break
        for cov_sel in (
            "input[type='file']#cover_letter",
            "input[type='file'][id*='cover' i]",
            "input[type='file'][name*='cover_letter' i]",
            "input[type='file'][name*='cover' i]",
        ):
            if cov_sel not in existing_sels and fill_buttons._locator_exists(page.locator(cov_sel)):
                required = False
                with contextlib.suppress(Exception):
                    required = page.locator(cov_sel).first.evaluate("""el => {
                      const group = el.closest('fieldset, .field, .form-group, .file-upload, [role=group]');
                      const label = group?.querySelector('legend, label, .upload-label')?.textContent || '';
                      return el.required || el.getAttribute('aria-required') === 'true' ||
                        !!el.closest('[aria-required=true]') || /[*✱][\\s\u2060:]*$|\\(required\\)/i.test(label.trim());
                    }""") is True
                file_inputs.append({"selector": cov_sel, "label": "Cover Letter", "required": required})
                break
        return file_inputs

    def _upload_one(self, fin: Any) -> bool:
        """Attach the right document to one file input. True when a resume file was set on
        the form, verified or not: the form may react to the file either way (Paylocity
        redraws its fields blank), so the after-upload passes run."""
        is_dict = isinstance(fin, dict)
        sel = fin.get("selector") if is_dict else None
        label = str(fin.get("label") or "") if is_dict else ""
        purpose = fill_widgets._attachment_purpose(
            label, str(sel or ""), self.hints,
            hint_key=str(fin.get("hint_key") or "") if is_dict else "",
            section=str(fin.get("section") or "") if is_dict else "",
        )
        frame_index = int(fin.get("frame_index") or 0) if is_dict else 0
        frames = self.frames
        upload_target = frames[frame_index] if 0 <= frame_index < len(frames) else self.page
        if not sel or not purpose:
            if sel and ("file", sel) not in self.uploaded_controls:
                self.uploads.append({
                    "selector": sel, "label": label, "purpose": "unknown", "verified": False,
                    "error": "Attachment purpose is ambiguous",
                })
                self.uploaded_controls.add(("file", sel))
            return False
        path = self.artifact_path(purpose)
        key = (purpose, f"{frame_index}:{sel}")
        if (purpose, frame_index) in self.verified_purposes:
            return False
        if (purpose, frame_index) in self.attempted_purposes:
            return False
        if key in self.uploaded_controls:
            return False
        self.uploaded_controls.add(key)
        self.attempted_purposes.add((purpose, frame_index))
        record = {"selector": sel, "label": label, "purpose": purpose}
        if purpose == "cover_letter":
            record["cover_letter_mode"] = self.settings.cover_letter_mode
        sha = upload_replace.artifact_sha256(path)
        existing_filename = fill_outcomes._attached_filename(upload_target, sel)
        # A native input replaces its file on the next upload; a listing widget needs the
        # old file removed first.
        replacing = False
        if isinstance(existing_filename, str) and existing_filename:
            replacing = self._keep_attached(record, existing_filename, sha, frame_index)
            if not replacing:
                return False
        if purpose == "cover_letter":
            if self._cover_in_background(bool(is_dict and fin.get("required"))):
                # Attached once the letter is written, at the end of the step. The frame's
                # other matches for this input stay skipped as attempted meanwhile.
                self.uploaded_controls.discard(key)
                self.cover_waiting.append(fin)
                return False
            action, written = self._cover_letter(bool(is_dict and fin.get("required")))
            if action == "skip":
                reason = f"Skipped: optional cover letter; setting is {self.settings.cover_letter_mode}"
                self.progress(reason)
                self.uploads.append({
                    **record, "state": "not_requested", "verified": False,
                    "reason": reason, "frame_index": frame_index,
                })
                return False
            path = self.cover_path
            sha = upload_replace.artifact_sha256(path)
            if written:
                record["reason"] = cover_on_demand.GENERATED_NOTE
        if not path or not Path(path).is_file():
            missing = (
                f"No {purpose} PDF saved; add one in Profile → Application"
                if purpose in {"transcript", "portfolio"}
                else f"No {purpose.replace('_', ' ')} artifact available"
            )
            self.uploads.append({
                **record, "verified": False, "error": missing, "frame_index": frame_index,
            })
            return False
        staged_path = fill_widgets._stage_attachment(
            path,
            purpose=purpose,
            applicant_name=self.applicant_name,
            role=self.pkt.role or self.app.role or "Application",
            out_dir=self.out_dir,
        )
        staged_name = Path(staged_path).name
        # Upload widgets that keep a file list (Workday) empty their input after each
        # upload; the listed filename is what says it is already attached.
        already_listed = False
        with contextlib.suppress(Exception):
            listed = upload_target.get_by_text(staged_name, exact=False).count()
            already_listed = isinstance(listed, int) and listed > 0
        if already_listed and not replacing:
            if not self._keep_attached(record, staged_name, sha, frame_index):
                self.progress(f"{purpose.replace('_', ' ')} already attached: {staged_name}")
                return False
            replacing = True
            if not upload_replace.remove_listed(upload_target, staged_name):
                self.uploads.append({
                    **record, "filename": staged_name, "verified": False,
                    "error": upload_replace.NOT_REPLACED_NOTE, "frame_index": frame_index,
                    **upload_replace.still_ours(self.previous_fill.uploads, purpose, staged_name),
                })
                return False
        if replacing:
            self.progress(f"replacing the earlier {purpose.replace('_', ' ')} upload")
        self.progress(f"uploading {purpose.replace('_', ' ')}: {staged_name}")
        uploaded = False
        upload_error = "Upload could not be verified on the form"
        try:
            with _app_upload(upload_target):
                uploaded = fill_widgets._set_and_verify_file(upload_target, sel, staged_path)
        except Exception as exc:  # noqa: BLE001
            upload_error = f"Browser rejected upload: {type(exc).__name__}"
            for frame in frames:
                try:
                    with _app_upload(frame):
                        uploaded = fill_widgets._set_and_verify_file(frame, sel, staged_path)
                    break
                except Exception:  # noqa: BLE001
                    continue
        self.uploads.append({
            **record, "filename": staged_name, "verified": uploaded,
            "error": "" if uploaded else upload_error, "frame_index": frame_index,
            "uploaded_by_app": uploaded, "artifact_sha256": sha, "artifact_path": str(path),
            **({"reason": upload_replace.REPLACED_NOTE} if uploaded and replacing else {}),
            # The outdated file may still be attached.
            **({} if uploaded or not replacing else upload_replace.still_ours(
                self.previous_fill.uploads, purpose, existing_filename or staged_name,
            )),
        })
        if not uploaded:
            return purpose == "resume"
        self.verified_purposes.add((purpose, frame_index))
        self.progress(f"{purpose.replace('_', ' ')} attachment verified")
        return purpose == "resume"

    def _attach_waiting_covers(self) -> None:
        """Attach the cover letter written in the background to the uploads that waited
        for it (`_cover_in_background`); `_cover_letter` waits for it to be ready."""
        waiting, self.cover_waiting = self.cover_waiting, []
        if waiting:
            self.progress("attaching the cover letter written for this form")
        for fin in waiting:
            frame_index = int(fin.get("frame_index") or 0) if isinstance(fin, dict) else 0
            self.attempted_purposes.discard(("cover_letter", frame_index))
            self._upload_one(fin)

    def _keep_attached(
        self, record: dict[str, Any], shown: str, sha: str, frame_index: int
    ) -> bool:
        """Record a file already attached as kept, unless it is the app's own outdated
        upload: True means replace it."""
        purpose = str(record["purpose"])
        whose = upload_replace.attached_by_app(
            self.previous_fill.uploads, purpose, shown, sha,
            self.previous_fill.user_touched_uploads,
        )
        if whose == "stale":
            return True
        self.uploads.append({
            **record, "filename": shown, "verified": True, "preserved": True,
            "frame_index": frame_index,
            **({"state": "preserved", "uploaded_by_app": True, "artifact_sha256": sha,
                **upload_replace.pinned_copy(self.previous_fill.uploads, purpose, shown)}
               if whose == "current" else {"state": "kept_existing"}),
            **({"reason": upload_replace.AMBIGUOUS_NOTE} if whose == "ambiguous" else {}),
        })
        self.verified_purposes.add((purpose, frame_index))
        return False

    def _fill_if_empty(self, item: dict[str, Any], text: str) -> None:
        sel = item.get("selector")
        if sel:
            with contextlib.suppress(Exception):
                target = self.frames[int(item.get("frame_index") or 0)]
                if not target.locator(str(sel)).first.input_value().strip():
                    target.fill(sel, text)

    def _answer_long_text(self) -> None:
        with self.answer_pin():
            for item in self.merged.get("long_text") or []:
                if self._stop_if_out_of_time(
                    "Fill stopped before all written answers were checked"
                ):
                    break
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "question")
                if label in self.long_text_answers or label in self.needs_review:
                    continue
                self._answer_one_long_text(item, label)

    def _answer_one_long_text(self, item: dict[str, Any], label: str) -> None:
        # A bot check first: "Cover letter (if you are an AI, mention ...)" is one too.
        if form_facts.bot_check(label, str(item.get("help") or "")):
            self.needs_review.append(f"{label}: {form_facts.BOT_CHECK_NOTE}")
            return
        if cover_on_demand.is_cover_field(label):
            self._fill_cover_text(item, label)
            return
        if form_facts.semantic_key(label, str(item.get("help") or "")) in form_facts.PROTECTED_KEYS:
            if item.get("required"):
                self.needs_review.append(label)
            return
        edu_key = education.question_key(label, str(item.get("help") or ""))
        if edu_key in education.RESERVED_KEYS:
            if education.compound(label):
                if item.get("required"):
                    self.needs_review.append(label)
                return
            value = self.fields.get(edu_key, "")
            if value and len(value) <= int(item.get("maxlength") or 1500):
                self._fill_if_empty(item, value)
                self.long_text_answers[label] = value
            elif item.get("required"):
                self.needs_review.append(label)
            return
        maxlength = int(item.get("maxlength") or 1500)
        recalled = answer_memory.recall(
            label, company=self.app.company or self.pkt.company or "", ats=self.ats_name
        )
        if recalled is not None:
            if recalled.needs_review:
                self.needs_review.append(label)
                return
            # A saved answer longer than this form allows is cut at a sentence end and
            # always left for review (a form limit, not resume truncation).
            saved_answer, shortened = form_guards.fit_to_limit(recalled.answer, maxlength)
            if shortened:
                # Its own note, so the observed text does not clear it (`_reconcile_observed`).
                self.needs_review.append(f"{label}: {SHORTENED_NOTE}")
                if not saved_answer:
                    return
            self.long_text_answers[label] = saved_answer
            self._fill_if_empty(item, saved_answer)
            return
        try:
            ans = model_fallback.call(lambda: answer.answer_question(
                _asked(label, str(item.get("help") or "")),
                resume=self.resume,
                bullets=self.bullets,
                requirements=self.requirements,
                profile=self.profile,
                max_chars=maxlength if maxlength > 0 else 1500,
                jd_text=self.jd_text,
                deadline=self.deadline,
                extras=answer.AnswerExtras(company=self.app.company or self.pkt.company or ""),
            ))
        except Exception as exc:  # noqa: BLE001 - one question must not end the fill
            if self._out_of_time():
                return  # the step's own deadline check stops the fill
            self.progress(f"could not draft an answer for {label[:60]} ({type(exc).__name__})")
            if item.get("required"):
                self.needs_review.append(f"{label}: {NOT_DRAFTED_NOTE}")
            return
        if ans.offenders or not ans.answer:
            self.needs_review.append(label)
            return
        self.long_text_answers[label] = ans.answer
        self._fill_if_empty(item, ans.answer)

    def _fill_cover_text(self, item: dict[str, Any], label: str) -> None:
        """A cover-letter text box follows the same rule as a cover-letter upload."""
        required = bool(item.get("required"))
        text = self._cover_text(required)
        if not text:
            if required:
                self.needs_review.append(label)
            return
        fitted, shortened = form_guards.fit_to_limit(text, int(item.get("maxlength") or 0))
        if shortened:
            self.needs_review.append(f"{label}: {SHORTENED_NOTE}")
            if not fitted:
                return
        self.long_text_answers[label] = fitted
        self._fill_if_empty(item, fitted)

    def _resolve_leftovers(self) -> None:
        for leftover in sorted(list(self.merged.get("leftovers") or []), key=_dependency_order):
            if self._stop_if_out_of_time("Fill stopped before all choices were checked"):
                break
            if isinstance(leftover, dict):
                self._resolve_leftover(leftover)

    def _accept_consent(self, leftover: dict[str, Any]) -> bool:
        """Tick a required consent checkbox on an iCIMS step (its sign-in step has an
        "I agree" privacy box the generic scan cannot key). True when it reads checked."""
        frame_index = int(leftover.get("frame_index") or 0)
        if not form_routes.tick_consent(self.frames[frame_index], leftover):
            return False
        label, selector = str(leftover.get("label") or ""), str(leftover["selector"])
        self.merged["filled"].append({
            "key": "consent", "label": label, "value": "checked",
            "selector": selector, "frame_index": frame_index,
        })
        done = {label, selector, selector.lstrip("#")}
        self.merged["required_empty"] = [
            item for item in self.merged.get("required_empty") or [] if item not in done
        ]
        self.merged["leftovers"] = [
            item for item in self.merged.get("leftovers") or [] if item is not leftover
        ]
        return True

    def _resolve_leftover(self, leftover: dict[str, Any]) -> None:
        needs_review = self.needs_review
        label = str(leftover.get("label") or "")
        if leftover.get("review"):
            # Answered with a guess (a location list's first option): its own note, so the
            # observed value does not clear it.
            needs_review.append(f"{label}: {leftover.get('reason')}")
            return
        if leftover.get("key") == "salary_expectation":
            if label not in needs_review:
                needs_review.append(label)
            return
        if label in needs_review:
            return
        if form_facts.bot_check(label, str(leftover.get("help") or "")):
            note = f"{label}: {form_facts.BOT_CHECK_NOTE}"
            if note not in needs_review:
                needs_review.append(note)
            return
        if form_facts.semantic_key(
            label, str(leftover.get("help") or ""),
        ) in form_facts.PROTECTED_KEYS:
            # Only the shared deterministic plan may answer these facts or notices.
            if leftover.get("required"):
                needs_review.append(label)
            return
        if (
            self.ats_name == "icims"
            and form_routes.is_required_consent(leftover)
            and self._accept_consent(leftover)
        ):
            return
        if leftover.get("type") == "combobox":
            target = self.frames[int(leftover.get("frame_index") or 0)]
            kept = fill_widgets.kept_choice(target, leftover, self.fields)
            if kept:
                self.merged["filled"].append({
                    "key": "existing", "label": label, "value": kept, "preserved": True,
                    "selector": leftover["selector"],
                    "frame_index": leftover.get("frame_index", 0),
                })
                self._settled(leftover)
                return
        if leftover.get("type") == "combobox" and leftover.get("key"):
            selected = fill_widgets._fill_declared_combobox(target, leftover, self.fields)
            if selected:
                self.merged["filled"].append({
                    "key": leftover["key"], "label": label, "value": selected,
                    "selector": leftover["selector"],
                    "frame_index": leftover.get("frame_index", 0),
                })
                self._settled(leftover)
                if leftover["key"] == "how_heard" and selected != self.fields.get("how_heard"):
                    self.other_chosen = True
                return
        edu_key = education.question_key(label, str(leftover.get("help") or ""))
        if leftover.get("key") in education.RESERVED_KEYS or edu_key in education.RESERVED_KEYS:
            if leftover.get("required"):
                reason = leftover.get("reason") or "Set Highest education completed in Profile"
                needs_review.append(f"{label}: {reason}")
            return
        recalled = answer_memory.recall(
            label, company=self.app.company or self.pkt.company or "", ats=self.ats_name,
            canonical_key=str(leftover.get("key") or ""),
        )
        if recalled is not None and recalled.needs_review:
            needs_review.append(label)
            return
        canned = (
            recalled.answer if recalled is not None
            else answer._profile_answer(label, self.profile)  # noqa: SLF001
        )
        if canned and leftover.get("selector"):
            try:
                self._set_canned_answer(leftover, canned)
                self.merged["filled"].append({
                    "key": "memory" if recalled is not None else "custom",
                    "label": label,
                    "value": canned,
                    "selector": leftover["selector"],
                })
            except Exception:  # noqa: BLE001
                needs_review.append(label)
        elif leftover.get("required"):
            needs_review.append(label)

    def _settled(self, leftover: dict[str, Any]) -> None:
        """A leftover now answered on the page is no longer left or required-empty."""
        merged = self.merged
        merged["leftovers"] = [item for item in merged["leftovers"] if item is not leftover]
        done = {str(leftover.get("label") or ""), str(leftover.get("selector") or "")}
        merged["required_empty"] = [
            item for item in merged.get("required_empty") or [] if item not in done
        ]

    def _set_canned_answer(self, leftover: dict[str, Any], canned: str) -> None:
        target = self.frames[int(leftover.get("frame_index") or 0)]
        selector = str(leftover["selector"])
        control_type = str(leftover.get("type") or "")
        if control_type == "select":
            target.locator(selector).first.select_option(label=canned)
        elif control_type == "radio":
            if not widget_actions._choose_radio_option(target, selector, canned):  # noqa: SLF001
                raise RuntimeError("No matching radio option")
        elif control_type in {"combobox", "button"}:
            if not widget_actions._select_combobox_option(target, selector, canned):  # noqa: SLF001
                raise RuntimeError("No matching dropdown option")
        elif not target.locator(selector).first.input_value().strip():
            target.fill(selector, canned)

    def _question_signature(self) -> frozenset[tuple[Any, ...]]:
        """Each visible question and each upload on the step as (frame, id, label,
        required, options): what tells that an answer revealed or changed a question.
        Keyed by the frame itself, so a frame added or removed moves no other's entries."""
        args = {"fields": {}, "hints": self.hints, "synonyms": fill_page._synonym_payload(),
                "scan": True}
        seen: set[tuple[Any, ...]] = set()
        for frame in self.page.frames:
            try:
                scanned = frame.evaluate(self.filler_js, args)
            except Exception:  # noqa: BLE001 - cross-origin frames fail evaluate
                continue
            scanned = scanned if isinstance(scanned, dict) else {}
            seen.update(
                (frame, q.get("qid"), q.get("label"), bool(q.get("required")),
                 tuple(q.get("options") or ()))
                for q in scanned.get("questions") or [] if isinstance(q, dict)
            )
            seen.update(
                (frame, f"file:{item.get('selector')}", item.get("label"),
                 bool(item.get("required")), ())
                for item in scanned.get("file_inputs") or [] if isinstance(item, dict)
            )
        return frozenset(seen)

    def _rescan_changed_questions(self, before: frozenset[tuple[Any, ...]]) -> None:
        """Fill what this step's answers revealed or changed (a State list after Country,
        "please specify" after "Other", a question turned required): a pass per change,
        at most `_MAX_RESCANS`; an unchanged step costs one scan."""
        for _ in range(_MAX_RESCANS):
            if self._out_of_time():
                return
            now = self._question_signature()
            if now == before:
                return
            self.progress(f"{len(now - before)} question(s) appeared or changed; filling them")
            self._rescan_revealed()
            before = now

    def _rescan_revealed(self) -> None:
        """Fill the step again and hand only what it had not seen to the usual handlers:
        new answers, choices, written answers, uploads and required questions."""
        merged = self.merged
        seen = {
            key: {
                (item.get("frame_index", 0), item.get("selector"))
                for item in merged[key] if isinstance(item, dict)
            }
            for key in ("filled", "leftovers", "long_text", "file_inputs")
        }
        new: dict[str, list[dict[str, Any]]] = {
            key: [] for key in ("leftovers", "long_text", "file_inputs")
        }
        for frame_index, frame in enumerate(self._sync_frames()):
            try:
                revealed = fill_widgets._fill_frame(
                    frame, self.filler_js, self.fields, self.hints, self.facts,
                    self.classify_unkeyed, self.classify_notices,
                )
            except Exception as exc:  # noqa: BLE001 - cross-origin frames fail evaluate
                _log.debug("rescan skipped frame %d: %s", frame_index, exc)
                continue
            if not isinstance(revealed, dict):
                continue
            merged["filled"].extend(
                {**item, "frame_index": frame_index} for item in revealed.get("filled") or []
                if isinstance(item, dict) and item.get("key") != "existing"
                and (frame_index, item.get("selector")) not in seen["filled"]
            )
            for key, items in new.items():
                items.extend(
                    {**item, "frame_index": frame_index} for item in revealed.get(key) or []
                    if isinstance(item, dict)
                    and (frame_index, item.get("selector")) not in seen[key]
                )
            merged["required_empty"].extend(
                item for item in revealed.get("required_empty") or []
                if item not in merged["required_empty"]
            )
        owns = self._flow_owned()
        if owns is not None:
            # A platform flow answered or listed these itself; handled again here they
            # come back as blank leftovers (SmartRecruiters' "*" questions, 2026-10-30).
            new = {key: [item for item in items if not owns(item)] for key, items in new.items()}
        self._handle_revealed(new)

    def _handle_revealed(self, new: dict[str, list[dict[str, Any]]]) -> None:
        """Uploads and written answers for the new controls alone (the step's earlier ones
        were handled), then the new leftovers."""
        merged = self.merged
        earlier = {key: merged[key] for key in ("long_text", "file_inputs")}
        try:
            merged["long_text"], merged["file_inputs"] = new["long_text"], new["file_inputs"]
            if new["file_inputs"]:
                self._upload_attachments()
            if new["long_text"]:
                self._answer_long_text()
        finally:
            for key, items in earlier.items():
                merged[key] = items + merged[key]
        for leftover in new["leftovers"]:
            merged["leftovers"].append(leftover)
            if self._stop_if_out_of_time("Fill stopped before all choices were checked"):
                break
            self._resolve_leftover(leftover)
