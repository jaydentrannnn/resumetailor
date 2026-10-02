"""Turning a source row into an application: prefilter, JD capture, logs, job settings."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import eligibility as eligibility_mod
from resume_tailor.apply.funnel import screen as screen_mod
from resume_tailor.apply.funnel import store, store_models
from resume_tailor.apply.funnel.screen import ScreenResult
from resume_tailor.web.schemas import ApplySettings, JobSettings

_LOG_LOCK = threading.Lock()

#: Below this many characters a fetched JD is treated as unusable — shared by the
#: nightly run (`_process_one`) and the per-row fetch retry, so a retry can't move
#: a row to `jd_fetched` with a scrap of text the nightly run would have rejected.
_MIN_USABLE_JD_CHARS = 100

def prefilter_screen(
    jd_text: str, role: str, settings: ApplySettings, *, seniority: str = ""
) -> ScreenResult:
    """The no-LLM part of screening: eligibility rules plus work-restriction blocks.

    Runs before JD extraction, so a posting it rejects costs no model call. A re-check
    passes the row's stored ``seniority`` so a screen-stage rejection is re-judged
    under the current rules without re-extracting.
    """
    elig = eligibility_mod.check_text(jd_text, settings.eligibility, role=role)
    blocks, evidence = screen_mod.check_blocks(jd_text, settings.screen)
    senior, senior_flags = screen_mod.seniority_reasons(seniority, role, settings.screen)
    reasons = [*elig.reasons, *blocks, *senior]
    return ScreenResult(
        passed=not reasons,
        reasons=reasons,
        flags=[*elig.flags, *senior_flags],
        evidence=evidence,
        seniority=seniority,
    )

def _today() -> str:
    """Return today's UTC date as ``YYYY-MM-DD``."""
    return datetime.now(UTC).strftime("%Y-%m-%d")

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()

def _log_path(date: str) -> Path:
    """Path for the daily text log under ``APPLICATIONS_OUTPUT_DIR``."""
    config.APPLICATIONS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return config.APPLICATIONS_OUTPUT_DIR / f"log-{date}.txt"

def _append_log(path: Path, line: str, log: Callable[[str], None]) -> None:
    """Write one line to the daily log file and the live logger."""
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    log(line)

def _application_from_row(
    row: SourceRow,
    *,
    canonical_key: str,
    group_key: str,
    final_url: str,
) -> store_models.Application:
    """Build a new ``Application`` record from one parsed README row."""
    ref = store_models.SourceRef(
        source=row.source_id or "simplify",
        source_job_id=row.job_id or "",
        url=row.application_link or "",
        first_seen=_now_iso(),
    )
    return store_models.Application(
        source=row.source_id or "simplify",
        source_job_id=row.job_id or "",
        company=row.company,
        role=row.role,
        location=row.location,
        posting_url=row.application_link or "",
        final_url=final_url,
        ats=fetch_jd.detect_ats(final_url or row.application_link or ""),
        sponsorship_ok=row.sponsorship_ok,
        citizenship_required=row.citizenship_required,
        notes=row.notes,
        discovered_at=_now_iso(),
        canonical_key=canonical_key,
        group_key=group_key,
        source_refs=[ref],
        age_days=row.age_days,
        posted_at=row.posted_at,
        salary=row.salary,
        eligibility_flags=list(row.flags),
    )

def _save_jd(source_job_id: str, text: str) -> str:
    """Persist JD text beside other application artifacts; return the path."""
    out_dir = config.APPLICATIONS_OUTPUT_DIR / source_job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "jd.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)

def _captured_jd(app: store_models.Application) -> fetch_jd.FetchResult | None:
    """The text the browser extension sent for this row, instead of fetching it again.

    A captured page (LinkedIn, Handshake, a careers page behind a login) often cannot be
    fetched without the applicant's session, so Prepare reuses what was captured.
    """
    if app.source != "extension" or not app.jd_text_path:
        return None
    try:
        text = Path(app.jd_text_path).read_text(encoding="utf-8")
    except OSError:
        return None
    if len(text.strip()) < _MIN_USABLE_JD_CHARS:
        return None
    url = app.final_url or app.posting_url
    return fetch_jd.FetchResult(
        final_url=url, ats=app.ats or fetch_jd.detect_ats(url), text=text, method="captured"
    )

def _prior_company(job_id: str) -> str:
    """Read company name from a prior run's ``run.json`` metadata."""
    run_path = config.OUTPUT_DIR / "jobs" / job_id / "run.json"
    if not run_path.is_file():
        return ""
    try:
        raw = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    metadata = raw.get("metadata") or {}
    return str(metadata.get("company") or "")

def _link_reused_packet(app: store_models.Application, prior_job_id: str) -> None:
    """Point ``app`` at an existing tailoring run without re-queueing."""
    app.reused_from_job_id = prior_job_id
    app.job_id = prior_job_id
    store.set_status(app, "ready", note=f"reused tailoring from {prior_job_id}")

def _job_settings(base: JobSettings, apply: ApplySettings) -> JobSettings:
    """Merge Apply knobs into one tailor run.

    Model routing is deliberately left as the Tailor tab's (``base``): Prepare tailors
    exactly like a Tailor-tab run would. ``apply.model_spec`` is the autofill model
    only — Fill's form-answer and choice-resolution calls — never the tailoring model.
    """
    settings = base.model_copy(deep=True)
    settings.no_expand = False
    if apply.cover_letter:
        settings.cover_letter = True
        settings.no_cover_letter = False
    return settings

def _settle_failed_prepare(
    previous: store_models.Application, source_job_id: str, *, error: str | None = None
) -> None:
    """Leave a row in an honest state after a Prepare that didn't reach ``ready``.

    A row that already had a packet (``ready`` or later) is restored, so a failed
    refresh never throws away good artifacts. A row that was still pre-ready keeps the
    new attempt's outcome (e.g. ``screened_out`` with its reasons) — restoring it could
    resurrect a stale ``tailoring`` whose job died with a server restart.
    """
    if previous.status not in store_models.PRE_READY_STATUSES:
        store.restore(previous)
        return
    current = store.get(source_job_id)
    if current is None:
        return
    if error is not None:
        if current.status == "tailoring":
            store.set_status(current, "tailor_failed", note=error)
        current.error = error
        store.upsert(current)
