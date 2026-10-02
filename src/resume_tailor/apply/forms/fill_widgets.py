"""Per-widget fill helpers: attachments, comboboxes, frames, observed and Workday fields."""

from __future__ import annotations

import contextlib
import json
import re
import shutil
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from resume_tailor import config
from resume_tailor.apply.answers import questions, widget_actions
from resume_tailor.apply.ats import workday_dropdowns, workday_page
from resume_tailor.apply.driver import browser
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.funnel import packet_models
from resume_tailor.pipeline import report
from resume_tailor.pipeline.jd import JobRequirements

from . import fill_page


def _attachment_purpose(
    label: str, selector: str, hints: dict[str, str], *, hint_key: str = "", section: str = "",
) -> str | None:
    """Classify one file control without relying on its position in the DOM.

    ``hint_key`` is what ``filler.js`` found by ``el.matches(hint)`` (Workday's generic
    "Upload a file (5MB max)" input is the resume by hint); ``section`` is the enclosing
    heading ("Resume/CV") for labels that name neither document.
    """
    text = f"{label} {section} {selector}".casefold()
    if "transcript" in text:
        return "transcript"
    # "Resume or portfolio" takes the resume, which every packet has.
    if ("portfolio" in text or "work sample" in text) and "resume" not in text:
        return "portfolio"
    if "cover" in text or "letter" in text:
        return "cover_letter"
    if hint_key == "resume_upload" or "resume" in text or "cv" in text:
        return "resume"
    for hint_selector, key in hints.items():
        if key == "resume_upload" and hint_selector == selector:
            return "resume"
    return None

def _set_and_verify_file(target: Any, selector: str, path: str) -> bool:
    """Verify either a retained input or an ATS replacement showing the filename."""
    control = target.locator(selector).first
    with browser.UPLOAD_LOCK:
        control.set_input_files(path, timeout=5000)
    expected = Path(path).name
    with contextlib.suppress(Exception):
        actual = control.evaluate(
            "el => el.files && el.files[0] ? el.files[0].name : ''",
            timeout=2000,
        )
        if str(actual) == expected:
            return True
    with contextlib.suppress(Exception):
        target.get_by_text(expected, exact=False).first.wait_for(state="visible", timeout=3000)
        return True
    return False

def _fill_declared_combobox(target: Any, item: dict[str, Any], fields: dict[str, str]) -> str | None:
    """Resolve a known fact from a visible option, never from typed search text."""
    key = str(item.get("key") or "")
    selector = str(item.get("selector") or "")
    if not selector or key in {"salary_expectation", ""}:
        return None
    planned = [str(item["value"])] if item.get("value") else []
    for value in dict.fromkeys([*planned, *field_matcher.choice_values(key, fields)]):
        if value and widget_actions._select_combobox_option(  # noqa: SLF001
            target, selector, value, key=key, phone_region=fields.get("phone_country_region", ""),
        ):
            return value
    return None

def _fill_frame(
    frame: Any, filler_js: str, fields: dict[str, str], hints: dict[str, str], facts: questions.Facts,
    classifier: questions.Classifier | None = None,
) -> Any:
    """Fill one frame: ``filler.js`` reads its questions, `questions` decides each one's
    key and answer (``classifier`` names what a choice question no rule covers asks),
    and the filler sets them (a failed read fills without a plan)."""
    args = {
        "fields": fields, "hints": hints, "synonyms": fill_page._synonym_payload(),
        "eeo": field_matcher.eeo_patterns(fields),
    }
    plan = None
    with contextlib.suppress(Exception):
        scanned = frame.evaluate(filler_js, {**args, "scan": True})
        plan = questions.plan_for(
            (scanned or {}).get("questions") or [], facts, classifier=classifier,
        )
    return frame.evaluate(filler_js, {**args, "plan": plan})

def _availability_note(earliest_start: str, jd_text: str) -> str | None:
    """Flag a declared availability later than an explicit program start in the JD."""
    try:
        available = date.fromisoformat(earliest_start)
    except ValueError:
        return None
    match = re.search(
        r"(?:program|internship)[^\n]{0,100}?\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}",
        jd_text,
        re.I,
    )
    if not match:
        return None
    try:
        starts = datetime.strptime(match.group(0)[match.start(1) - match.start():].replace(",", ""), "%B %d %Y").date()
    except ValueError:
        return None
    if available <= starts:
        return None
    return f"Availability {available.isoformat()} is after the posting's program start {starts.isoformat()}; review before submitting"

def _observe_fields(page: Any, filler_js: str, hints: dict[str, str], attempted: dict[tuple[int, str], dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    """Read current selected values without filling any new answer."""
    observed: dict[tuple[int, str], dict[str, Any]] = {}
    for frame_index, frame in enumerate(page.frames):
        with contextlib.suppress(Exception):
            current = frame.evaluate(
                filler_js, {"fields": {}, "hints": hints, "synonyms": fill_page._synonym_payload()}
            )
            for item in current.get("filled") or []:
                selector = item.get("selector")
                if not selector:
                    continue
                prior = attempted.get((frame_index, selector), {})
                observed[(frame_index, selector)] = {
                    **item,
                    "key": prior.get("key") or item.get("key"),
                    "preserved": bool(prior.get("preserved")),
                    "frame_index": frame_index,
                }
                if prior.get("corrected") and prior.get("previous"):
                    observed[(frame_index, selector)].update(
                        corrected=True,
                        previous=prior["previous"],
                        reason_text=(
                            "Corrected after the resume upload "
                            f"(the form had “{prior['previous']}”)"
                        ),
                    )
    return observed

def _correct_resume_prefill(
    page: Any, frames: list[Any], filler_js: str, fields: dict[str, Any], hints: dict[str, str]
) -> list[dict[str, Any]]:
    """E3: put back contact facts an ATS's resume parser overwrote after the upload.

    Greenhouse, Workday and iCIMS read the uploaded PDF and fill name, email, phone and
    links from it, sometimes over what the fill already typed. ``filler.js`` in
    ``correct`` mode rewrites only those facts, only where they disagree with the
    profile, and reports each one with the value it replaced.
    """
    page.wait_for_timeout(1500)
    corrected: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(frames):
        with contextlib.suppress(Exception):
            result = frame.evaluate(
                filler_js,
                {
                    "fields": fields,
                    "hints": hints,
                    "synonyms": fill_page._synonym_payload(),
                    "correct": True,
                },
            )
            for key in ("filled", "leftovers"):
                corrected.extend(
                    {**item, "frame_index": frame_index}
                    for item in (result or {}).get(key) or []
                    if isinstance(item, dict)
                )
    return corrected

def _stage_attachment(
    source: str,
    *,
    purpose: Literal["resume", "cover_letter", "transcript", "portfolio"],
    applicant_name: str,
    role: str,
    out_dir: Path,
) -> str:
    """Copy an internal artifact to the user-facing filename sent to the ATS."""
    source_path = Path(source)
    suffix = source_path.suffix or ".pdf"
    if purpose == "resume":
        filename = report.export_filename(applicant_name, role, suffix=suffix)
    elif purpose in {"transcript", "portfolio"}:
        # Not tailored per role: "Ada Lovelace Transcript.pdf".
        resume_name = report.export_filename(applicant_name, "x", suffix=suffix)
        filename = resume_name.split(" Resume - ", 1)[0] + f" {purpose.title()}{suffix}"
    else:
        resume_name = report.export_filename(applicant_name, role, suffix=suffix)
        filename = resume_name.replace(f" Resume - ", " Cover Letter - ", 1)
    attachment_dir = out_dir / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    staged = attachment_dir / filename
    if source_path.resolve() != staged.resolve():
        shutil.copyfile(source_path, staged)
    return str(staged)

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

def _fill_workday_experience_and_education(
    page: Any,
    pkt: packet_models.Packet,
    progress: Callable[[str], None],
) -> tuple[list[dict[str, str]], list[str]]:
    """Fill only Workday rows whose identity is unambiguous; preserve manual rows."""
    from resume_tailor.apply.ats import workday_repeaters

    # The Skills prompt runs just before and can leave its popup (and the full-viewport
    # dismiss layer) open over the Add buttons (F5, 2026-09): closed first, and again
    # when an Add press is blocked.
    return workday_repeaters.fill(
        page, pkt, progress, select=workday_dropdowns.select_listbox, dismiss=workday_page.close_stray_popups,
    )

def _guard_file_chooser(page: Any, progress: Callable[[str], None]) -> None:
    """Swallow any OS file picker a stray click opens while the fill runs.

    Attachments are set with ``set_input_files`` and never need the picker; with a
    ``filechooser`` listener attached, Playwright intercepts the dialog instead of
    showing it, so nothing is left blocking the applicant's browser. The interception
    ends with the CDP connection, before the tab is handed over.
    """
    def _blocked(_chooser: Any) -> None:
        # No page calls from inside a sync Playwright event handler: log only.
        progress("blocked an unexpected file picker")

    with contextlib.suppress(Exception):
        page.on("filechooser", _blocked)

def _commit_workday_textareas(frames: list[Any], items: list[Any]) -> None:
    """Re-enter the filler's textarea answers with real input events, then blur.

    Workday's questionnaire textareas ignore a value set from page JS (live 2026-09-24,
    Excellus: the salary box showed "$18/hour" yet validated as empty); its text inputs
    accept one, so only textareas are re-committed.
    """
    for item in items:
        if not isinstance(item, dict) or item.get("preserved") or not item.get("selector"):
            continue
        index = int(item.get("frame_index") or 0)
        target = frames[index] if 0 <= index < len(frames) else frames[0]
        with contextlib.suppress(Exception):
            control = target.locator(str(item["selector"])).first
            if control.evaluate("el => el.tagName") != "TEXTAREA":
                continue
            control.fill(str(item.get("value") or ""), timeout=3000)
            control.evaluate("el => el.blur()")
