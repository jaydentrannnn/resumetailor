"""After an application is sent: interview prep, follow-up notes and "no reply" marks.

Prep and notes are drafted from what the employer received (`apply/funnel/sent_copy.py`)
on the Light task model, like other app tools, and are only shown: nothing here is sent.
Registered before the applications router so ``/api/applications/follow-ups`` is not
read as an application id.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.funnel import followup_due, outcomes, sent_copy, store_models
from resume_tailor.apply.funnel import store as apply_store
from resume_tailor.content import data
from resume_tailor.infra import atomic
from resume_tailor.pipeline import followup_note, interview_prep
from resume_tailor.web import job_routing

router = APIRouter()


class PrepRequest(BaseModel):
    stage: interview_prep.Stage


class PrepList(BaseModel):
    preps: list[interview_prep.InterviewPrep]


class FollowupRequest(BaseModel):
    kind: followup_note.Kind = "follow_up"
    channel: followup_note.Channel = "email"
    recipient: str = Field(default="", max_length=120)


class NoReplyRequest(BaseModel):
    application_ids: list[str] = Field(max_length=500)


class NoReplyResult(BaseModel):
    updated: list[str]
    #: Application id -> why it was left alone.
    skipped: dict[str, str]


def _app(source_job_id: str) -> store_models.Application:
    app = apply_store.get(source_job_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"Unknown application {source_job_id!r}.")
    return app


def _copy(app: store_models.Application) -> sent_copy.SentCopy:
    copy = sent_copy.load(app)
    if copy is None:
        raise HTTPException(
            status_code=409, detail="This application has no tailored resume to work from."
        )
    return copy


def _prep_dir(app: store_models.Application) -> Path:
    return config.APPLICATIONS_OUTPUT_DIR / app.source_job_id / "interview_prep"


def _notes(app: store_models.Application) -> list[str]:
    """Earlier events with something the student wrote, oldest first."""
    return [
        f"{event.occurred_on or event.recorded_at[:10]} "
        f"{event.type.replace('_', ' ')}: {event.note}"
        for event in outcomes.live_events(app)
        if event.note
    ]


@router.get("/api/applications/follow-ups", response_model=followup_due.DueList)
def follow_ups_due() -> followup_due.DueList:
    """Sent applications due a follow-up or thank-you, and those gone silent."""
    return followup_due.due_list(apply_store.rows_view().values(), followup_due.today())


@router.post("/api/applications/no-reply", response_model=NoReplyResult)
def mark_no_reply(body: NoReplyRequest) -> NoReplyResult:
    """Record "no reply" (``ghosted``) on rows that are still stale; never "rejected"."""
    updated: list[str] = []
    skipped: dict[str, str] = {}
    today = followup_due.today()
    for source_job_id in dict.fromkeys(body.application_ids):

        def mutate(app: store_models.Application) -> None:
            found = followup_due.state(app, today)
            if not found.stale:
                raise ValueError(found.reason or (
                    f"Sent {found.days_since_sent} days ago, under "
                    f"{followup_due.STALE_AFTER_DAYS}."
                ))
            outcomes.add_event(
                app, "ghosted", occurred_on=today.isoformat(),
                note=f"No reply {found.days_since_sent} days after sending",
            )

        try:
            apply_store.update(source_job_id, mutate)
        except apply_store.StaleApplication:
            skipped[source_job_id] = "Unknown application."
        except ValueError as exc:
            skipped[source_job_id] = str(exc)
        else:
            updated.append(source_job_id)
    return NoReplyResult(updated=updated, skipped=skipped)


@router.get("/api/applications/{source_job_id}/interview-prep", response_model=PrepList)
def saved_preps(source_job_id: str) -> PrepList:
    """Every prep saved for this application, one per round."""
    folder = _prep_dir(_app(source_job_id))
    preps = []
    for stage in interview_prep.STAGES:
        saved = atomic.read_cached(folder / f"{stage}.json", interview_prep.InterviewPrep)
        if saved is not None:
            preps.append(saved)
    return PrepList(preps=preps)


@router.post(
    "/api/applications/{source_job_id}/interview-prep",
    response_model=interview_prep.InterviewPrep,
)
def make_prep(source_job_id: str, body: PrepRequest) -> interview_prep.InterviewPrep:
    """Draft prep for one round from what was sent, and save it (replacing that round's)."""
    app = _app(source_job_id)
    copy = _copy(app)
    try:
        with job_routing.pinned_role("light"):
            prep = interview_prep.prepare(
                body.stage, resume=data.load(), role=app.role, company=app.company,
                requirements=copy.requirements, bullets=copy.bullets,
                cover_letter=copy.cover_letter, jd_text=copy.jd_text, gaps=copy.gaps,
                notes=_notes(app), based_on=copy.based_on,
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    folder = _prep_dir(app)
    folder.mkdir(parents=True, exist_ok=True)
    atomic.write_text(folder / f"{body.stage}.json", prep.model_dump_json(indent=2) + "\n")
    return prep


@router.post(
    "/api/applications/{source_job_id}/follow-up", response_model=followup_note.FollowupNote
)
def draft_follow_up(source_job_id: str, body: FollowupRequest) -> followup_note.FollowupNote:
    """Draft a follow-up or thank-you note; the student copies it and marks it sent.

    A row with no tailored run still gets a note; with no sent bullets it may claim
    nothing about the candidate (the guard falls back to the plain template)."""
    app = _app(source_job_id)
    copy = sent_copy.load(app)
    try:
        with job_routing.pinned_role("light"):
            return followup_note.draft(
                body.kind, body.channel, resume=data.load(), role=app.role,
                company=app.company, bullets=copy.bullets if copy else {},
                jd_text=copy.jd_text if copy else "",
                sent_on=outcomes.sent_on(app) or "", recipient=body.recipient.strip(),
                notes=_notes(app),
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
