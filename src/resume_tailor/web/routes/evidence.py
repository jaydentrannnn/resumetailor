"""Evidence for the master resume: GitHub repositories and documents the student adds, and
the resume items proposed from them (`pipeline/evidence.py`, on the Light model).

Nothing reaches the resume until the student decides an item: Add to resume writes it
through the resume route's save (version, backup, skill refresh) under
`template_ops.LOCK`, as their own edit; Matching only keeps a skill in the evidence
file's matching layer, read beside inferred skills and never written to the resume;
Dismiss keeps it out of later scans. A scan is started by hand, one source at a time,
and its model call runs outside the lock under a snapshot of the profile's context.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from resume_tailor import config
from resume_tailor.content import data, evidence_accept, evidence_store
from resume_tailor.content.data import MasterResume
from resume_tailor.content.evidence_store import EvidenceSource, Proposal, SourceKind
from resume_tailor.importing import evidence_sources, github_evidence
from resume_tailor.infra.polite_fetch import Fetcher
from resume_tailor.pipeline import evidence
from resume_tailor.web import job_routing, template_ops
from resume_tailor.web.routes.resume import _write_master_resume

router = APIRouter()

MAX_TEXT = 50_000


class GitHubRequest(BaseModel):
    #: A username, or a link to one repository.
    target: str = Field(min_length=1, max_length=300)


class TextRequest(BaseModel):
    kind: SourceKind = "other"
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    scan: bool = True


class MatchingRequest(BaseModel):
    target_entry_id: str = ""


class SourceView(BaseModel):
    """A source without its text (``chars`` says how much there is)."""

    id: str
    kind: SourceKind
    title: str
    url: str | None = None
    added_at: str = ""
    flags: list[str] = Field(default_factory=list)
    attribution: str = ""
    commit_share: float | None = None
    languages: list[str] = Field(default_factory=list)
    scanned_at: str = ""
    dropped: int = 0
    drop_reasons: dict[str, int] = Field(default_factory=dict)
    model: str = ""
    chars: int = 0


class EvidenceView(BaseModel):
    sources: list[SourceView] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    matching: dict[str, list[str]] = Field(default_factory=dict)
    #: The username in the resume's GitHub field, to prefill the form.
    github_user: str = ""
    github_token: bool = False
    warnings: list[str] = Field(default_factory=list)


class AddResponse(BaseModel):
    evidence: EvidenceView
    #: The saved master resume, for the editor to adopt.
    resume: dict[str, Any]


def _load_resume() -> MasterResume | None:
    try:
        return data.load()
    except (FileNotFoundError, ValueError):
        return None


def _view(warnings: list[str] | None = None) -> EvidenceView:
    stored = evidence_store.load()
    resume = _load_resume()
    return EvidenceView(
        sources=[
            SourceView(**s.model_dump(exclude={"text", "sha"}), chars=len(s.text))
            for s in stored.sources
        ],
        proposals=stored.proposals,
        matching=stored.matching,
        github_user=github_evidence.username(resume.contact.github) if resume else "",
        github_token=bool(config.credential("GITHUB_TOKEN")),
        warnings=warnings or [],
    )


def _snapshot() -> config.RunContext:
    with template_ops.LOCK:
        return config.default_context()


def _scan(context: config.RunContext, source_id: str) -> None:
    """Read proposals from one source and store them, under ``context``."""
    with config.use_context(context):
        resume = _load_resume()
        if resume is None:
            raise HTTPException(status_code=409, detail="Save your resume before scanning.")
        source = evidence_store.source(evidence_store.load(), source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        try:
            with job_routing.pinned_role("light"):
                result = evidence.scan(resume, source)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        with evidence_store.update() as stored:
            current = evidence_store.source(stored, source_id)
            if current is None:  # removed while the model was reading it
                raise HTTPException(status_code=404, detail="Source not found")
            evidence_store.merge_scan(stored, source_id, result.proposals)
            current.scanned_at = evidence_store.now()
            current.dropped = sum(result.dropped.values())
            current.drop_reasons = dict(result.dropped)
            current.model = result.model


def _add_source(context: config.RunContext, source: EvidenceSource, scan: bool) -> EvidenceView:
    with config.use_context(context):
        with evidence_store.update() as stored:
            source = evidence_store.put_source(stored, source)
        if scan and not source.scanned_at:
            _scan(context, source.id)
        return _view()


@router.get("/api/evidence", response_model=EvidenceView)
def get_evidence() -> EvidenceView:
    with template_ops.LOCK:
        return _view()


@router.post("/api/evidence/github", response_model=EvidenceView)
def add_github(body: GitHubRequest) -> EvidenceView:
    """List the repositories behind a username or one repository link. No scan."""
    context = _snapshot()
    with config.use_context(context):
        resume = _load_resume()
        user = github_evidence.username(resume.contact.github) if resume else ""
        try:
            with Fetcher() as fetcher:
                repos, warnings = github_evidence.read(body.target, fetcher, user=user)
        except github_evidence.GitHubError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with evidence_store.update() as stored:
            for repo in repos:
                evidence_store.put_source(stored, evidence_sources.from_repo(repo))
        if not repos:
            warnings.append("No public repositories were found.")
        return _view(warnings)


@router.post("/api/evidence/text", response_model=EvidenceView)
def add_text(body: TextRequest) -> EvidenceView:
    try:
        source = evidence_sources.from_text(body.kind, body.title, body.text)
    except evidence_sources.SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _add_source(_snapshot(), source, body.scan)


@router.post("/api/evidence/file", response_model=EvidenceView)
async def add_file(
    file: UploadFile = File(...),
    kind: SourceKind = Form("other"),
    title: str = Form(""),
    scan: bool = Form(True),
) -> EvidenceView:
    raw = await file.read(evidence_sources.MAX_FILE_BYTES + 1)
    try:
        source = await run_in_threadpool(
            evidence_sources.from_file, kind, title, file.filename or "", raw
        )
    except evidence_sources.SourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await run_in_threadpool(_add_source, _snapshot(), source, scan)


@router.post("/api/evidence/sources/{source_id}/scan", response_model=EvidenceView)
def scan_source(source_id: str) -> EvidenceView:
    context = _snapshot()
    _scan(context, source_id)
    with config.use_context(context):
        return _view()


@router.delete("/api/evidence/sources/{source_id}", response_model=EvidenceView)
def delete_source(source_id: str) -> EvidenceView:
    with template_ops.LOCK:
        with evidence_store.update() as stored:
            if not evidence_store.remove_source(stored, source_id):
                raise HTTPException(status_code=404, detail="Source not found")
        return _view()


def _decided(stored: evidence_store.Evidence, pid: str, states: tuple[str, ...]) -> Proposal:
    item = evidence_store.proposal(stored, pid)
    if item is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if item.state not in states:
        state = item.state.replace("_", " ")
        raise HTTPException(status_code=409, detail=f"This item is already {state}.")
    return item


@router.post("/api/evidence/proposals/{pid}/add", response_model=AddResponse)
def add_to_resume(pid: str, body: evidence_accept.AddRequest) -> AddResponse:
    """Write the item, as the student edited it, into the master resume."""
    with template_ops.LOCK:
        resume = _load_resume()
        if resume is None:
            raise HTTPException(status_code=409, detail="Save your resume first.")
        with evidence_store.update() as stored:
            item = _decided(stored, pid, ("pending", "matching_only"))
            try:
                saved, where = evidence_accept.add(resume, item, body)
            except evidence_accept.AcceptError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            _write_master_resume(saved, note="added from evidence")
            if item.state == "matching_only":
                evidence_store.drop_from_matching(stored, item.target_entry_id, item.text)
            item.state, item.decided_at, item.added_to = "added", evidence_store.now(), where
        return AddResponse(evidence=_view(), resume=saved.model_dump(by_alias=True))


@router.post("/api/evidence/proposals/{pid}/matching-only", response_model=EvidenceView)
def keep_for_matching(pid: str, body: MatchingRequest) -> EvidenceView:
    """Use a skill to match postings without putting it on the resume."""
    with template_ops.LOCK:
        resume = _load_resume()
        entries = {e.id for s in resume.entry_sections for e in s.entries} if resume else set()
        with evidence_store.update() as stored:
            item = _decided(stored, pid, ("pending",))
            if item.kind != "skill":
                raise HTTPException(
                    status_code=422, detail="Only a skill can be kept for matching."
                )
            target = body.target_entry_id or item.target_entry_id
            if target not in entries:
                raise HTTPException(
                    status_code=422, detail="That resume entry no longer exists; pick another."
                )
            evidence_store.keep_for_matching(stored, target, item.text)
            item.target_entry_id = target
            item.state, item.decided_at, item.added_to = "matching_only", evidence_store.now(), ""
        return _view()


@router.post("/api/evidence/proposals/{pid}/dismiss", response_model=EvidenceView)
def dismiss(pid: str) -> EvidenceView:
    with template_ops.LOCK:
        with evidence_store.update() as stored:
            item = _decided(stored, pid, ("pending",))
            item.state, item.decided_at = "dismissed", evidence_store.now()
        return _view()


@router.post("/api/evidence/proposals/{pid}/reopen", response_model=EvidenceView)
def reopen(pid: str) -> EvidenceView:
    """Undo Dismiss or Matching only. An added item is edited in the resume instead."""
    with template_ops.LOCK:
        with evidence_store.update() as stored:
            item = _decided(stored, pid, ("dismissed", "matching_only"))
            if item.state == "matching_only":
                evidence_store.drop_from_matching(stored, item.target_entry_id, item.text)
            item.state, item.decided_at = "pending", ""
        return _view()
