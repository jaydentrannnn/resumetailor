"""Uploads, long-text answers and leftover-field resolution within one wizard step."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.apply.answers import answer, answer_memory, widget_actions
from resume_tailor.apply.forms import form_guards, form_routes

from . import fill_buttons, fill_outcomes, fill_state, fill_widgets


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
                file_inputs.append({"selector": cov_sel, "label": "Cover Letter"})
                break
        return file_inputs

    def _upload_one(self, fin: Any) -> bool:
        """Attach the right document to one file input. True when a resume was uploaded."""
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
        path = (
            self.resume_path if purpose == "resume"
            else self.pkt.artifacts.get(f"{purpose}_pdf")
            if purpose in {"transcript", "portfolio"}
            else self.cover_path
        )
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
        existing_filename = fill_outcomes._attached_filename(upload_target, sel)
        if isinstance(existing_filename, str) and existing_filename:
            self.uploads.append({
                **record, "filename": existing_filename, "verified": True, "preserved": True,
                "frame_index": frame_index,
            })
            self.verified_purposes.add((purpose, frame_index))
            return False
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
        if already_listed:
            self.uploads.append({
                **record, "filename": staged_name, "verified": True, "preserved": True,
                "frame_index": frame_index,
            })
            self.verified_purposes.add((purpose, frame_index))
            self.progress(f"{purpose.replace('_', ' ')} already attached: {staged_name}")
            return False
        self.progress(f"uploading {purpose.replace('_', ' ')}: {staged_name}")
        uploaded = False
        upload_error = "Upload could not be verified on the form"
        try:
            uploaded = fill_widgets._set_and_verify_file(upload_target, sel, staged_path)
        except Exception as exc:  # noqa: BLE001
            upload_error = f"Browser rejected upload: {type(exc).__name__}"
            for frame in frames:
                try:
                    uploaded = fill_widgets._set_and_verify_file(frame, sel, staged_path)
                    break
                except Exception:  # noqa: BLE001
                    continue
        self.uploads.append({
            **record, "filename": staged_name, "verified": uploaded,
            "error": "" if uploaded else upload_error, "frame_index": frame_index,
        })
        if not uploaded:
            return False
        self.verified_purposes.add((purpose, frame_index))
        self.progress(f"{purpose.replace('_', ' ')} attachment verified")
        return purpose == "resume"

    def _fill_if_empty(self, item: dict[str, Any], text: str) -> None:
        sel = item.get("selector")
        if sel:
            with contextlib.suppress(Exception):
                target = self.frames[int(item.get("frame_index") or 0)]
                if not target.locator(str(sel)).first.input_value().strip():
                    target.fill(sel, text)

    def _answer_long_text(self) -> None:
        with config.pinned(self.settings.model_spec):
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
                self.needs_review.append(label)
                if not saved_answer:
                    return
            self.long_text_answers[label] = saved_answer
            self._fill_if_empty(item, saved_answer)
            return
        ans = answer.answer_question(
            label,
            resume=self.resume,
            bullets=self.bullets,
            requirements=self.requirements,
            profile=self.profile,
            max_chars=maxlength if maxlength > 0 else 1500,
            jd_text=self.jd_text,
            deadline=self.deadline,
            extras=answer.AnswerExtras(company=self.app.company or self.pkt.company or ""),
        )
        if ans.offenders or not ans.answer:
            self.needs_review.append(label)
            return
        self.long_text_answers[label] = ans.answer
        self._fill_if_empty(item, ans.answer)

    def _resolve_leftovers(self) -> None:
        for leftover in list(self.merged.get("leftovers") or []):
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
        if (
            self.ats_name == "icims"
            and form_routes.is_required_consent(leftover)
            and self._accept_consent(leftover)
        ):
            return
        if leftover.get("type") == "combobox" and leftover.get("key"):
            target = self.frames[int(leftover.get("frame_index") or 0)]
            selected = fill_widgets._fill_declared_combobox(target, leftover, self.fields)
            if selected:
                self.merged["filled"].append({
                    "key": leftover["key"], "label": label, "value": selected,
                    "selector": leftover["selector"],
                    "frame_index": leftover.get("frame_index", 0),
                })
                if leftover["key"] == "how_heard" and selected != self.fields.get("how_heard"):
                    self.other_chosen = True
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

    def _rescan_revealed_choices(self) -> None:
        merged = self.merged
        known = {
            (item.get("frame_index", 0), item.get("selector"))
            for item in merged["leftovers"] if isinstance(item, dict)
        }
        known_filled = {
            (item.get("frame_index", 0), item.get("selector"))
            for item in merged["filled"] if isinstance(item, dict)
        }
        for frame_index, frame in enumerate(self.frames):
            with contextlib.suppress(Exception):
                revealed = fill_widgets._fill_frame(
                    frame, self.filler_js, self.fields, self.hints, self.facts,
                    self.classify_unkeyed,
                )
                merged["filled"].extend(
                    {**item, "frame_index": frame_index} for item in revealed.get("filled") or []
                    if isinstance(item, dict) and item.get("key") != "existing"
                    and (frame_index, item.get("selector")) not in known_filled
                )
                for item in revealed.get("leftovers") or []:
                    identity = (frame_index, item.get("selector"))
                    if identity in known or item.get("type") != "combobox":
                        continue
                    item = {**item, "frame_index": frame_index}
                    merged["leftovers"].append(item)
                    known.add(identity)
                    selected = fill_widgets._fill_declared_combobox(frame, item, self.fields)
                    if selected:
                        merged["filled"].append({
                            "key": item.get("key"), "label": item.get("label"),
                            "value": selected, "selector": item.get("selector"),
                            "frame_index": frame_index,
                        })
