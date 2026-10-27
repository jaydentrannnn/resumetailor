"""Send a finished Tailor run to Apply (audit #29).

A run made on the Tailor page has no application behind it. Sending it names the
posting: an application already tracked for that posting gets this run's files, or a
new one is created with them. Either way it lands `ready`, so its next step on Apply is
Fill. A run whose resume or template changed since is refused: tailor it again first.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.discovery import fetch_jd, identity
from resume_tailor.apply.funnel import daily_rows, operations, preparation, store, store_models
from resume_tailor.web import run_inputs
from resume_tailor.web.routes.applications import _application_out
from resume_tailor.web.schemas import ApplicationOut

from . import run_lookup

router = APIRouter()


class SendToApplyRequest(BaseModel):
    posting_url: str = Field(min_length=1, max_length=2000)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=300)


class SendToApplyResponse(BaseModel):
    application: ApplicationOut
    #: False when the posting was already tracked and now uses this run.
    created: bool
    #: What still stands in Fill's way (`preparation.check`); empty when it can Fill.
    reasons: list[str] = Field(default_factory=list)


def _source_job_id(key: str) -> str:
    return "tailor-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _finished_run(job_id: str) -> dict:
    raw = run_lookup._load_run_json(job_id)
    if raw is None or raw.get("workspace_id", config.active_workspace_id()) != (
        config.active_workspace_id()
    ):
        raise HTTPException(status_code=404, detail="Unknown run")
    if raw.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="Only a finished run can be sent to Apply")
    stale = run_inputs.stale(config.OUTPUT_DIR / "jobs" / job_id)
    if stale:
        raise HTTPException(
            status_code=409,
            detail=f"Your {' and '.join(stale)} changed since this run. Tailor it again, then send it.",
        )
    return raw


def _link(app: store_models.Application, job_id: str) -> None:
    app.job_id = job_id
    app.reused_from_job_id = None
    app.error = None
    daily_rows.adopt_run_coverage(app, daily_rows.run_coverage(job_id))
    store.set_status(app, "ready", note=f"tailored on the Tailor page (run {job_id})")


@router.post("/api/jobs/{job_id}/send-to-apply", response_model=SendToApplyResponse)
def send_to_apply(job_id: str, body: SendToApplyRequest) -> SendToApplyResponse:
    """Track the posting this run was tailored for, with the run's files, ready to Fill."""
    raw = _finished_run(job_id)
    url = body.posting_url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Enter the posting's link (https://…)")
    key = identity.canonical_key(url)
    existing = store.get(key)
    if existing is not None:
        if existing.archived_at or existing.status in store_models.TERMINAL_STATUSES:
            raise HTTPException(
                status_code=409,
                detail=f"{existing.company} · {existing.role} is already {existing.status}",
            )
        try:
            with operations.rows_idle([existing.source_job_id]):
                app = store.update(existing.source_job_id, lambda row: _link(row, job_id))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SendToApplyResponse(
            application=_application_out(app), created=False,
            reasons=preparation.check(app).reasons,
        )

    metadata = raw.get("metadata") or {}
    company = body.company.strip() or str(metadata.get("company") or "").strip()
    role = body.role.strip() or str(raw.get("title") or "").strip()
    if not company:
        raise HTTPException(status_code=422, detail="Enter the company this posting is from")
    now = daily_rows._now_iso()
    source_job_id = _source_job_id(key)
    app = store_models.Application(
        source="tailor",
        source_job_id=source_job_id,
        company=company,
        role=role or "Unknown role",
        posting_url=url,
        final_url=url,
        ats=fetch_jd.detect_ats(url),
        discovered_at=now,
        canonical_key=key,
        group_key=identity.group_key(company, role),
        source_refs=[store_models.SourceRef(
            source="tailor", source_job_id=source_job_id, url=url, first_seen=now,
        )],
    )
    jd_file = config.OUTPUT_DIR / "jobs" / job_id / "jd.txt"
    if jd_file.is_file():
        daily_rows.save_jd(app, jd_file.read_text(encoding="utf-8"), None)
    _link(app, job_id)
    app = store.upsert(app)
    return SendToApplyResponse(
        application=_application_out(app), created=True, reasons=preparation.check(app).reasons
    )
