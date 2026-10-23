"""Email updates: job emails Claude Desktop read, proposed as outcomes for the student.

Claude Desktop's own Gmail connector does the reading; the MCP server asks here for the
search to run (`search-plan`), posts what it found (`messages`), and the student
accepts or dismisses each proposal in the app. Nothing is written to an application
without that click, and no email text goes to a model here (`apply/funnel/mail_signals`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resume_tailor.apply.funnel import mail_inbox, mail_signals, outcomes, store_models
from resume_tailor.apply.funnel import store as apply_store

router = APIRouter()

#: Companies a search names before it falls back to application-system senders only
#: (Gmail search strings have a practical length limit).
_MAX_COMPANIES = 40
_SUBJECT_WORDS = ("application", "interview", "assessment", "offer", "candidacy")


class SearchPlan(BaseModel):
    #: Run as-is in Gmail search. Never limited to the inbox: archived and filtered
    #: mail must be found too.
    query: str
    since: str
    companies: list[str]
    sender_domains: list[str]


class MessagesRequest(BaseModel):
    messages: list[mail_inbox.IncomingMail] = Field(max_length=mail_inbox.MAX_MESSAGES)


class MessagesResult(mail_inbox.IngestResult):
    pending: int = 0


class Candidate(BaseModel):
    id: str
    company: str
    role: str
    stage: str


class ProposalView(mail_inbox.Proposal):
    company: str = ""
    role: str = ""
    #: The application's hiring stage now ("Applied", "Interviewing", ...).
    stage: str = ""
    options: list[Candidate] = Field(default_factory=list)


class ProposalList(BaseModel):
    proposals: list[ProposalView]


class AcceptRequest(BaseModel):
    signal: mail_signals.Signal | None = None
    app_id: str | None = Field(default=None, max_length=300)


def _rows() -> list[store_models.Application]:
    return list(apply_store.rows_view().values())


def _candidate(app: store_models.Application) -> Candidate:
    return Candidate(id=app.source_job_id, company=app.company, role=app.role,
                     stage=outcomes.hiring_progress(app).label or "Not sent")


def _active(app: store_models.Application) -> bool:
    """Sent or prepared, and not closed: an employer may still write about it."""
    progress = outcomes.hiring_progress(app)
    if progress.closed in ("rejected", "withdrawn", "offer_declined"):
        return False
    return app.status in outcomes.SENT or app.status in (
        "ready", "awaiting_review", "awaiting_otp", "fill_failed",
    )


def _quote(text: str) -> str:
    return '"' + text.replace('"', "").strip() + '"'


def plan(rows: list[store_models.Application], since: str) -> SearchPlan:
    names = {app.company.strip() for app in rows if _active(app)} - {""}
    companies = sorted(names, key=str.casefold)
    hosts = set(mail_signals.ATS_DOMAINS)
    # Gmail's from: already matches subdomains (hire.lever.co under lever.co).
    domains = sorted(h for h in hosts if not any(h.endswith("." + o) for o in hosts))
    terms = [f"from:{domain}" for domain in domains]
    if len(companies) <= _MAX_COMPANIES:
        terms += [_quote(company) for company in companies]
    else:
        terms += [f"subject:{word}" for word in _SUBJECT_WORDS]
    query = f"after:{since.replace('-', '/')} -in:sent -in:drafts ({' OR '.join(terms)})"
    return SearchPlan(query=query, since=since, companies=companies, sender_domains=domains)


def _view(
    proposal: mail_inbox.Proposal, by_id: dict[str, store_models.Application]
) -> ProposalView:
    view = ProposalView(**proposal.model_dump())
    if (app := by_id.get(proposal.app_id or "")) is not None:
        view.company, view.role = app.company, app.role
        view.stage = outcomes.hiring_progress(app).label or "Not sent"
    keys = proposal.candidates
    if not proposal.app_id and not keys and proposal.state == "pending":
        # Nothing matched: offer every application an employer may still write about.
        keys = [key for key, app in by_id.items() if _active(app)]
    options = [_candidate(by_id[key]) for key in keys if key in by_id]
    view.options = sorted(options, key=lambda c: (c.company.casefold(), c.role.casefold()))
    return view


@router.get("/api/mail/search-plan", response_model=SearchPlan)
def search_plan() -> SearchPlan:
    """The Gmail search Claude Desktop should run for new job emails."""
    return plan(_rows(), mail_inbox.search_since())


@router.post("/api/mail/messages", response_model=MessagesResult)
def post_messages(body: MessagesRequest) -> MessagesResult:
    """Read job emails into proposals (nothing is recorded on an application)."""
    result = mail_inbox.ingest(body.messages, _rows())
    return MessagesResult(**result.model_dump(), pending=len(mail_inbox.pending()))


@router.get("/api/mail/proposals", response_model=ProposalList)
def list_proposals() -> ProposalList:
    by_id = {app.source_job_id: app for app in _rows()}
    return ProposalList(proposals=[_view(p, by_id) for p in mail_inbox.pending()])


@router.post("/api/mail/proposals/{proposal_id}/accept", response_model=ProposalView)
def accept_proposal(proposal_id: str, body: AcceptRequest) -> ProposalView:
    """Record one proposal on its application (or the one the student picked)."""
    try:
        proposal, app = mail_inbox.accept(proposal_id, signal=body.signal, app_id=body.app_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="That email update is gone.") from exc
    except apply_store.StaleApplication as exc:
        raise HTTPException(status_code=404, detail="That application no longer exists.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _view(proposal, {app.source_job_id: app})


@router.post("/api/mail/proposals/{proposal_id}/dismiss", response_model=ProposalView)
def dismiss_proposal(proposal_id: str) -> ProposalView:
    try:
        proposal = mail_inbox.dismiss(proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="That email update is gone.") from exc
    return _view(proposal, {})
