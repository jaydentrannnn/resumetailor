"""Turning a source row into an application: prefilter, JD capture, logs, job settings."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.answers import profile
from resume_tailor.apply.discovery import fetch_jd, identity
from resume_tailor.apply.discovery.source_rows import SourceRow
from resume_tailor.apply.funnel import eligibility as eligibility_mod
from resume_tailor.apply.funnel import language_gate, store, store_models
from resume_tailor.apply.funnel import screen as screen_mod
from resume_tailor.apply.funnel.screen import ScreenResult
from resume_tailor.pipeline import coverage as coverage_mod
from resume_tailor.pipeline.posting_guard import GuardFindings
from resume_tailor.web.schemas import ApplySettings, JobSettings

_LOG_LOCK = threading.Lock()

#: Below this many characters a fetched JD is treated as unusable — shared by the
#: nightly run (`_process_one`) and the per-row fetch retry, so a retry can't move
#: a row to `jd_fetched` with a scrap of text the nightly run would have rejected.
_MIN_USABLE_JD_CHARS = 100

def prefilter_screen(
    jd_text: str, role: str, settings: ApplySettings, *, seniority: str = ""
) -> ScreenResult:
    """The no-LLM part of screening: eligibility rules, work-restriction blocks and the
    spoken languages the posting requires (against the applicant profile's).

    Runs before JD extraction, so a posting it rejects costs no model call. A re-check
    passes the row's stored ``seniority`` so a screen-stage rejection is re-judged
    under the current rules without re-extracting.
    """
    elig = eligibility_mod.check_text(jd_text, settings.eligibility, role=role)
    blocks, evidence = screen_mod.check_blocks(jd_text, settings.screen)
    senior, senior_flags = screen_mod.seniority_reasons(seniority, role, settings.screen)
    spoken, spoken_flags, spoken_evidence = language_gate.check(
        jd_text, profile.load_languages()
    )
    reasons = [*elig.reasons, *blocks, *senior, *spoken]
    return ScreenResult(
        passed=not reasons,
        reasons=reasons,
        flags=[*elig.flags, *senior_flags, *spoken_flags],
        evidence=[*evidence, *spoken_evidence],
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

def save_jd(
    app: store_models.Application, text: str, found: GuardFindings | None
) -> None:
    """Save the row's JD with what the posting guard found on the way in.

    ``found`` is None for text read back from this row's own saved file (a captured
    page), whose findings were recorded when it was first saved.
    """
    app.jd_text_path = _save_jd(app.source_job_id, text)
    if found is not None:
        app.posting_guard = found

#: Job boards the backend never fetches, or whose pages need the applicant's session.
_BOARDS = frozenset({"linkedin", "indeed", "handshake"})


def _on_ats(url: str) -> bool:
    """Whether ``url`` names an ATS posting: a known ATS host, or a page whose key names a
    requisition (a ``gh_jid`` on a company's careers page)."""
    if not url:
        return False
    ats = fetch_jd.detect_ats(url)
    if ats in _BOARDS:
        return False
    return ats not in {"other", "unknown"} or not identity.is_placeholder_key(
        identity.canonical_key(url)
    )


def fetch_target(app: store_models.Application) -> tuple[str, str | None]:
    """Where to fetch the row's JD, and the key for an ATS feed lookup.

    A row found through a short link (go.vansh.nyc, zapply, Adzuna) keeps that link as
    its ``posting_url``, while an earlier fetch may have learned the ATS page it leads to
    (``final_url``). Fetching that page lets the ATS paths run: Workday and iCIMS by URL,
    the feeds by key. A wrapper link that never resolved (the sighting was offline) is
    resolved now. The row's stored key is its identity and never changes here; a
    placeholder one only gives way to the resolved page's key for the feed lookup.
    """
    posting, final = app.posting_url or "", app.final_url or ""
    if posting and not _on_ats(final):
        final = identity.resolve_final_url(posting)  # unchanged unless a wrapper host
    url = final if _on_ats(final) and not _on_ats(posting) else posting or final
    key = app.canonical_key or ""
    if identity.is_placeholder_key(key) and url:
        key = identity.canonical_key(url)
    return url, None if identity.is_placeholder_key(key) else key


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
    adopt_run_coverage(app, run_coverage(prior_job_id))
    store.set_status(app, "ready", note=f"reused tailoring from {prior_job_id}")


def run_coverage(job_id: str) -> tuple[int, int, int | None] | None:
    """``(matched, total, on_page)`` must-haves from a finished run, if any.

    The run's latest funnel decides (`coverage.read`: re-scored or re-measured after a
    bullet edit, else the report's); a run saved before funnels uses its report, with
    ``on_page`` None.
    """
    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    if not (out_dir / "run.json").is_file():
        return None
    if (funnel := coverage_mod.read(out_dir)) is not None:
        return funnel.in_resume, funnel.total, funnel.on_page
    try:
        raw = json.loads((out_dir / "run.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    report = raw.get("report") if isinstance(raw, dict) else None
    matched = report.get("coverage_matched") if isinstance(report, dict) else None
    total = report.get("coverage_total") if isinstance(report, dict) else None
    if not (isinstance(matched, int) and isinstance(total, int)):
        return None
    page = report.get("page_coverage_matched")
    return matched, total, page if isinstance(page, int) else None


def adopt_run_coverage(
    app: store_models.Application, coverage: tuple[int, int, int | None] | None
) -> bool:
    """Show the tailor run's must-have counts on the row; True when the row changed.

    Once a row has a run, the run report is the figure of record: the row and the
    report then always agree, including rows screened before screening and tailoring
    shared one JD extraction. The page figure is what the Apply table shows.
    """
    if app.screen is None or coverage is None:
        return False
    matched, total, page = coverage
    screen = app.screen
    if (screen.coverage_matched, screen.coverage_total, screen.page_coverage_matched) == (
        matched, total, page
    ):
        return False
    screen.coverage_matched = matched
    screen.coverage_total = total
    screen.coverage = matched / total if total else 1.0
    screen.page_coverage_matched = page
    return True

def _job_settings(
    base: JobSettings, apply: ApplySettings, *, ats: str | None = None
) -> JobSettings:
    """Merge Apply knobs into one tailor run.

    Model routing is deliberately left as the Tailor tab's (``base``): Prepare tailors
    exactly like a Tailor-tab run would. ``apply.model_spec`` is the autofill model
    only — Fill's form-answer and choice-resolution calls — never the tailoring model.

    The experience expansion is written only for an ``ats`` whose fill pastes it
    (`preparation.needs_expansion`); without ``ats`` it is always written. Other rows
    generate it on demand from their detail page.

    The cover letter follows Apply's `cover_letter_mode`, never the Tailor tab's switch:
    written here only for ``every``; the other modes leave it to Fill
    (`cover_on_demand`), since most applications never ask for one.
    """
    from resume_tailor.apply.funnel import preparation

    settings = base.model_copy(deep=True)
    settings.no_expand = ats is not None and not preparation.needs_expansion(ats)
    every = apply.cover_letter_mode == "every"
    settings.cover_letter = every
    settings.no_cover_letter = not every
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
