"""Record what happened after an application went out (`apply/funnel/outcomes.py`).

Unlike the status route, these work on archived (Done) rows: marking a row submitted
archives it, and the interview comes later. Each write is one atomic `store.update`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from resume_tailor.apply.funnel import outcomes
from resume_tailor.apply.funnel import store as apply_store

from ..schemas import ApplicationOut, OutcomeCorrection, OutcomeRequest
from .applications import _application_out

router = APIRouter()


def _write(source_job_id: str, mutate) -> ApplicationOut:
    try:
        app = apply_store.update(source_job_id, mutate)
    except apply_store.StaleApplication as exc:
        detail = f"Unknown application {source_job_id!r}."
        raise HTTPException(status_code=404, detail=detail) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown event") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _application_out(app)


@router.post("/api/applications/{source_job_id}/outcomes", response_model=ApplicationOut)
def record_outcome(source_job_id: str, body: OutcomeRequest) -> ApplicationOut:
    """Add one outcome event (an interview, an offer, a rejection, ...)."""
    return _write(
        source_job_id,
        lambda app: outcomes.add_event(
            app, body.type, occurred_on=body.occurred_on, note=body.note, source=body.source
        ),
    )


@router.patch(
    "/api/applications/{source_job_id}/outcomes/{event_id}", response_model=ApplicationOut
)
def correct_outcome(source_job_id: str, event_id: str, body: OutcomeCorrection) -> ApplicationOut:
    """Correct an event (its replacement is recorded) or remove it; both keep history."""

    def mutate(app) -> None:
        if body.void:
            outcomes.void_event(app, event_id)
        else:
            outcomes.correct_event(
                app, event_id, type=body.type, occurred_on=body.occurred_on, note=body.note
            )

    return _write(source_job_id, mutate)
