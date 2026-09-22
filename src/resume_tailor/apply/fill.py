"""Deterministic ATS form fill via the host browser over CDP (Edge recommended).

Injects ``filler.js``, uploads resume PDF, drafts long-text leftovers through
``answer.answer_question``, then either stops for review or auto-submits when
``ats`` is listed in ``ApplySettings.auto_submit_ats``.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config, data
from resume_tailor.apply import answer, ats_hints, browser, packet as apply_packet
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply import store
from resume_tailor.apply.store import FillResult
from resume_tailor.jd import JobRequirements
from resume_tailor.web.schemas import ApplySettings, JobSettings

_lock = threading.Lock()
_running_for: str | None = None
_progress: dict[str, FillResult] = {}


class FillBusyError(RuntimeError):
    """Raised when another fill is already in progress."""


def decide_submit_action(
    *,
    ats: str,
    settings: ApplySettings,
    ready_to_submit: bool,
) -> Literal["auto_submit", "awaiting_review"]:
    """Return ``auto_submit`` when policy B allows it, else ``awaiting_review``."""
    if ats.lower() == "workday":
        # Workday never auto-submits, regardless of settings — see CLAUDE.md. Account
        # creation/CAPTCHA/multi-step flows there make unattended submission unsafe.
        return "awaiting_review"
    auto = ats.lower() in {a.lower() for a in settings.auto_submit_ats}
    if auto and ready_to_submit:
        return "auto_submit"
    return "awaiting_review"


def fill_busy() -> bool:
    """Return True while any fill worker is active."""
    with _lock:
        return _running_for is not None


def get_fill_result(source_job_id: str) -> FillResult | None:
    """Return in-memory or persisted fill outcome for ``source_job_id``."""
    if source_job_id in _progress:
        return _progress[source_job_id]
    app = store.get(source_job_id)
    if app is None or app.fill is None:
        return None
    if isinstance(app.fill, FillResult):
        return app.fill
    return FillResult.model_validate(app.fill)


def _load_filler_js() -> str:
    """Read the packaged filler script."""
    return (
        resources.files("resume_tailor.apply")
        .joinpath("filler.js")
        .read_text(encoding="utf-8")
    )


def _load_readiness_js() -> str:
    """Read the packaged required-empty checker, if present."""
    path = resources.files("resume_tailor.apply").joinpath("filler_readiness.js")
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return "( ) => ({ required_empty: [] })"


def _synonym_payload() -> list[list[str]]:
    """Serialise ``SYNONYMS`` for the page evaluate argument."""
    return [[pat, key] for pat, key in ats_hints.SYNONYMS]


def _hint_selector(hints: dict[str, str], special: str) -> str | None:
    """Return the CSS selector mapped to a reserved hint value like ``submit``."""
    if special in hints and special not in ats_hints.CANONICAL_FIELD_KEYS:
        return special
    for selector, value in hints.items():
        if value == special:
            return selector
    return None


def _job_artifacts(job_id: str) -> tuple[dict[str, str], JobRequirements | None, str]:
    """Load bullets, requirements, and JD text for the answer stage."""
    out = config.OUTPUT_DIR / "jobs" / job_id
    bullets: dict[str, str] = {}
    bullets_path = out / "bullets.json"
    if bullets_path.is_file():
        raw = json.loads(bullets_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            bullets = {str(k): str(v) for k, v in raw.items()}
    requirements: JobRequirements | None = None
    req_path = out / "requirements.json"
    if req_path.is_file():
        requirements = JobRequirements.model_validate_json(
            req_path.read_text(encoding="utf-8")
        )
    jd_text = ""
    jd_path = out / "jd.txt"
    if jd_path.is_file():
        jd_text = jd_path.read_text(encoding="utf-8")
    return bullets, requirements, jd_text


def fill_application(
    source_job_id: str,
    *,
    settings: ApplySettings | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> FillResult:
    """Fill one application's ATS form; leave the tab open under policy A."""
    def progress(msg: str) -> None:
        """Forward a progress line when a callback is set."""
        if on_progress:
            on_progress(msg)

    app = store.get(source_job_id)
    if app is None:
        raise KeyError(f"Unknown application {source_job_id!r}")
    if settings is None:
        from resume_tailor import workspace

        settings = JobSettings.model_validate(workspace.load_settings()["defaults"]).apply

    if not app.job_id:
        result = FillResult(error="No tailored job_id on application", status="fill_failed")
        store.set_status(app, "fill_failed", note=result.error or "")
        app.fill = result
        store.upsert(app)
        return result

    store.set_status(app, "filling", note="")
    store.upsert(app)
    progress("building packet")
    pkt = apply_packet.build_packet(app.job_id)
    profile, _ = profile_mod.load_profile()
    resume = data.load()
    bullets, requirements, jd_text = _job_artifacts(app.job_id)
    filler_js = _load_filler_js()
    readiness_js = _load_readiness_js()
    hints = dict(pkt.field_hints) or ats_hints.hints_for(app.ats)
    fields = dict(pkt.fields)
    if profile.f1_opt_eligible is not None:
        fields["f1_opt_eligible"] = "Yes" if profile.f1_opt_eligible else "No"
    if profile.pronouns:
        fields["pronouns"] = profile.pronouns
    url = app.final_url or app.posting_url

    try:
        with browser.cdp_browser() as pw_browser:
            context = (
                pw_browser.contexts[0]
                if pw_browser.contexts
                else pw_browser.new_context()
            )
            page = context.new_page()
            progress(f"navigating {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_load_state("networkidle", timeout=45_000)

            for click_sel in ats_hints.ATS_PRE_FILL_CLICKS.get(app.ats, []):
                try:
                    loc = page.locator(click_sel).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=3000)
                        page.wait_for_timeout(500)
                except Exception:  # noqa: BLE001 - optional pre-clicks
                    pass

            merged: dict[str, Any] = {
                "filled": [],
                "leftovers": [],
                "long_text": [],
                "file_inputs": [],
                "required_empty": [],
                "frames_skipped": 0,
            }
            frames = page.frames
            for frame in frames:
                try:
                    partial = frame.evaluate(
                        filler_js,
                        {
                            "fields": fields,
                            "hints": hints,
                            "synonyms": _synonym_payload(),
                        },
                    )
                except Exception:  # noqa: BLE001 - cross-origin frames fail evaluate
                    merged["frames_skipped"] = int(merged["frames_skipped"]) + 1
                    continue
                if not isinstance(partial, dict):
                    continue
                for key in ("filled", "leftovers", "long_text", "file_inputs", "required_empty"):
                    merged[key].extend(partial.get(key) or [])
                merged["frames_skipped"] += int(partial.get("frames_skipped") or 0)

            # File uploads via Playwright (cannot set from page JS).
            resume_path = pkt.artifacts.get("resume_pdf") or pkt.artifacts.get("resume_docx")
            cover_path = pkt.artifacts.get("cover_pdf") or pkt.artifacts.get("cover_docx")
            file_inputs = list(merged.get("file_inputs") or [])
            for idx, fin in enumerate(file_inputs):
                sel = fin.get("selector") if isinstance(fin, dict) else None
                label = (fin.get("label") or "").lower() if isinstance(fin, dict) else ""
                path = resume_path
                if idx > 0 or "cover" in label:
                    path = cover_path or resume_path
                if not sel or not path or not Path(path).is_file():
                    continue
                try:
                    page.set_input_files(sel, path)
                except Exception:  # noqa: BLE001
                    for frame in frames:
                        try:
                            frame.set_input_files(sel, path)
                            break
                        except Exception:  # noqa: BLE001
                            continue

            long_text_answers: dict[str, str] = {}
            needs_review: list[str] = []
            with config.pinned(settings.model_spec):
                for item in merged.get("long_text") or []:
                    if not isinstance(item, dict):
                        continue
                    label = str(item.get("label") or "question")
                    maxlength = int(item.get("maxlength") or 1500)
                    ans = answer.answer_question(
                        label,
                        resume=resume,
                        bullets=bullets,
                        requirements=requirements,
                        profile=profile,
                        max_chars=maxlength if maxlength > 0 else 1500,
                        jd_text=jd_text,
                    )
                    if ans.offenders or not ans.answer:
                        needs_review.append(label)
                        continue
                    long_text_answers[label] = ans.answer
                    sel = item.get("selector")
                    if sel:
                        try:
                            page.fill(sel, ans.answer)
                        except Exception:  # noqa: BLE001
                            pass

            for leftover in merged.get("leftovers") or []:
                if not isinstance(leftover, dict):
                    continue
                label = str(leftover.get("label") or "")
                canned = answer._profile_answer(label, profile)  # noqa: SLF001
                if canned and leftover.get("selector"):
                    try:
                        page.fill(str(leftover["selector"]), canned)
                        merged["filled"].append(
                            {
                                "key": "custom",
                                "label": label,
                                "value": canned,
                                "selector": leftover["selector"],
                            }
                        )
                    except Exception:  # noqa: BLE001
                        needs_review.append(label)
                else:
                    needs_review.append(label)

            required_empty: list[str] = []
            try:
                ready = page.evaluate(readiness_js)
                if isinstance(ready, list):
                    required_empty = [str(item) for item in ready]
                elif isinstance(ready, dict):
                    required_empty = list(ready.get("required_empty") or [])
            except Exception:  # noqa: BLE001
                required_empty = list(merged.get("required_empty") or [])

            ready_to_submit = len(required_empty) == 0 and not needs_review

            out_dir = config.APPLICATIONS_OUTPUT_DIR / source_job_id
            out_dir.mkdir(parents=True, exist_ok=True)
            shot = out_dir / "fill.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                shot = None  # type: ignore[assignment]

            submit_action = "awaiting_review"
            confirmation = ""
            final_status = "awaiting_review"
            action = decide_submit_action(
                ats=app.ats or pkt.ats,
                settings=settings,
                ready_to_submit=ready_to_submit,
            )
            if action == "auto_submit":
                submit_sel = _hint_selector(hints, "submit")
                confirm_text = hints.get("confirmation_text") or "thank you"
                if submit_sel:
                    try:
                        page.click(submit_sel, timeout=10_000)
                        page.wait_for_load_state("networkidle", timeout=30_000)
                        body = page.inner_text("body")
                        if confirm_text.lower() in body.lower():
                            confirmation = confirm_text
                            submit_action = "auto_submit"
                            final_status = "submitted"
                        else:
                            confirmation = "missing"
                            submit_action = "auto_submit"
                            final_status = "submit_unconfirmed"
                    except Exception as exc:  # noqa: BLE001
                        confirmation = str(exc)
                        submit_action = "auto_submit"
                        final_status = "fill_failed"

            result = FillResult(
                filled=list(merged.get("filled") or []),
                leftovers=list(merged.get("leftovers") or [])
                + [{"label": n, "reason": "needs_review"} for n in needs_review],
                long_text_answers=long_text_answers,
                required_empty=required_empty,
                ready_to_submit=ready_to_submit,
                submit_action=submit_action,
                confirmation=confirmation,
                screenshot_path=str(shot) if shot else None,
                status=final_status,
            )
            (out_dir / "fill.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
            # Policy B: leave the tab open when awaiting human review.
            store.set_status(app, final_status, note=submit_action)  # type: ignore[arg-type]
            app.fill = result
            store.upsert(app)
            _progress[source_job_id] = result
            progress(f"done status={final_status}")
            return result
    except Exception as exc:  # noqa: BLE001
        result = FillResult(error=str(exc), status="fill_failed")
        store.set_status(app, "fill_failed", note=str(exc))
        app.fill = result
        app.error = str(exc)
        store.upsert(app)
        _progress[source_job_id] = result
        return result


def start_fill_async(
    source_job_id: str,
    settings: ApplySettings | None = None,
) -> None:
    """Start ``fill_application`` on a daemon thread; raises ``FillBusyError`` if busy."""
    global _running_for
    with _lock:
        if _running_for is not None:
            raise FillBusyError(f"Fill already running for {_running_for}")
        status = browser.browser_status()
        if not status.reachable:
            raise RuntimeError(status.error or "Browser CDP unreachable")
        _running_for = source_job_id

    def _worker() -> None:
        """Run fill then clear the busy flag."""
        global _running_for
        try:
            fill_application(source_job_id, settings=settings)
        finally:
            with _lock:
                _running_for = None

    threading.Thread(target=_worker, name=f"fill-{source_job_id}", daemon=True).start()
