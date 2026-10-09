"""Vocabulary dictionary and proposal routes (the Vocabulary page)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from resume_tailor import config
from resume_tailor.content import data, libraries, library_models
from resume_tailor.pipeline import jd, propose
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.workspaces import _busy_conflict
from resume_tailor.web.schemas import (
    LibraryEffectiveOut,
    LibraryProposalOut,
    LibraryStateResponse,
    ProposalApproveRequest,
    ProposalGenerateRequest,
    ProposalRejectRequest,
    VocabularyAddRequest,
    VocabularyEntryOut,
    VocabularyHideRequest,
    VocabularyItemOut,
    VocabularyRemoveRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _library_proposal_out(
    p: library_models.LibraryProposal, effective: library_models.EffectiveLibrary
) -> LibraryProposalOut:
    target = (p.canonical or "").strip().lower()
    return LibraryProposalOut(
        id=p.id, kind=p.kind, alias=p.alias, canonical=p.canonical, verb=p.verb,
        family=p.family, rationale=p.rationale, source=p.source, created_at=p.created_at,
        target_exists=p.kind != "tag_alias" or target in effective.terms,
    )


def _library_state_response(*, warning: str | None = None) -> LibraryStateResponse:
    state = libraries.read_workspace_state()
    effective = libraries.resolve_effective()
    return LibraryStateResponse(
        entries=[
            VocabularyEntryOut(
                kind=e.kind, name=e.name, builtin=e.builtin, hidden=e.hidden,
                items=[VocabularyItemOut(value=i.value, builtin=i.builtin, hidden=i.hidden)
                       for i in e.items],
            )
            for e in libraries.dictionary_view()
        ],
        effective=LibraryEffectiveOut(
            term_count=len(effective.terms),
            tag_alias_count=len(effective.tag_aliases),
            verb_count=len(effective.verb_index),
            fingerprint=libraries.effective_fingerprint(effective),
        ),
        diagnostics=effective.diagnostics,
        proposals=[_library_proposal_out(p, effective) for p in state.proposals],
        warning=warning,
    )


@router.get("/api/libraries", response_model=LibraryStateResponse)
def get_libraries() -> LibraryStateResponse:
    """The whole dictionary (built-in + yours, hidden flagged) and pending suggestions."""
    return _library_state_response()


def _library_write_conflict() -> HTTPException:
    return _busy_conflict("editing the vocabulary")


def _edit_vocabulary(
    edit: Callable[[library_models.UserVocabulary], library_models.UserVocabulary],
) -> LibraryStateResponse:
    """Apply one edit to the app-wide additions under the usual write guards.

    Vocabulary edits never touch the master resume (tags are canonicalised at match
    time), so there is no impact preview or backup — only the busy/lock guard, because
    a running job reads `config.TAG_ALIASES`.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        try:
            updated = edit(libraries.read_user_vocabulary())
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.write_user_vocabulary(updated)
        libraries.reload()
        return _library_state_response()


@router.post("/api/libraries/additions", response_model=LibraryStateResponse)
def add_vocabulary(body: VocabularyAddRequest) -> LibraryStateResponse:
    """Add a term, another spelling of a term, or an opening verb to a family."""
    if body.kind == "term":
        return _edit_vocabulary(lambda user: libraries.add_term(user, body.value))
    if body.kind == "alias":
        return _edit_vocabulary(lambda user: libraries.add_alias(user, body.value, body.target))
    return _edit_vocabulary(lambda user: libraries.add_verb(user, body.value, body.target))


@router.post("/api/libraries/additions/remove", response_model=LibraryStateResponse)
def remove_vocabulary(body: VocabularyRemoveRequest) -> LibraryStateResponse:
    """Delete one of the user's own entries (built-ins can only be hidden)."""
    return _edit_vocabulary(lambda user: libraries.remove_addition(user, body.kind, body.value))


@router.post("/api/libraries/hidden", response_model=LibraryStateResponse)
def hide_vocabulary(body: VocabularyHideRequest) -> LibraryStateResponse:
    """Hide (or show again) one built-in term, spelling or verb."""
    return _edit_vocabulary(
        lambda user: libraries.set_hidden(user, body.kind, body.value, body.hidden)
    )


@router.post("/api/libraries/proposals", response_model=LibraryStateResponse)
def generate_library_proposals(body: ProposalGenerateRequest) -> LibraryStateResponse:
    """Draft new vocabulary-library proposals from the master resume's own near-miss
    keyword gaps (against an optional pasted JD) and unclassified opening verbs.

    Does not check `busy()` — generating a draft changes nothing effective, so a
    tailoring job may run alongside it. The LLM call itself runs unlocked (it can take
    a while and must not freeze the Template tab); the active workspace id is captured
    first and re-checked once `template_ops.LOCK` is held for the write, so a profile
    switch mid-call cannot land a draft in the wrong profile's queue.

    Not a tailoring job, so `config._ACTIVE` is never populated for it (only the job
    runner does that) — both LLM calls below are pinned to `config.ONE_OFF_PROFILE`
    so this never silently falls
    through to `backend_for`'s claude default on a fresh server with no Anthropic key,
    regardless of the user's saved Model setting.
    """
    workspace_id_at_start = config.active_workspace_id()
    try:
        resume = data.load()
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    known_tags = sorted({t for b in resume.all_bullets() for t in b.tags})
    jd_text = body.jd_text.strip()

    unmatched: list[tuple[str, str]] = []
    if jd_text:
        try:
            with config.pinned(config.ONE_OFF_PROFILE):
                requirements = jd.extract(jd_text, known_tags=known_tags)
            unmatched = propose.near_miss_alias_candidates(requirements, resume)
        except Exception as exc:
            # Broad on purpose — see the matching comment on the import route's tag
            # pass: a raw backend SDK error (not `LLMError`/`RuntimeError`) must still
            # come back as a warning, not a 500.
            return _library_state_response(
                warning=f"Could not read the pasted job description: {exc}"
            )

    unknown_verbs = propose.unclassified_opening_verbs(resume)
    effective = libraries.resolve_effective()

    filtered: list[library_models.LibraryProposal] = []
    warning: str | None = None
    if unmatched or unknown_verbs:
        try:
            with config.pinned(config.ONE_OFF_PROFILE):
                raw = propose.propose_vocabulary(
                    known_tags=known_tags,
                    unmatched=unmatched,
                    unknown_verbs=unknown_verbs,
                    families=effective.verb_families,
                    jd_text=jd_text,
                )
        except Exception as exc:
            return _library_state_response(warning=f"Could not draft suggestions: {exc}")

        rejected = libraries.read_workspace_state().rejected
        filtered = propose.filter_proposals(
            raw,
            known_tags=known_tags,
            effective=effective,
            rejected=rejected,
            source="run" if jd_text else "manual",
        )
        if not filtered:
            warning = "The model did not find any new suggestions worth proposing."

    with template_ops.LOCK:
        if config.active_workspace_id() != workspace_id_at_start:
            raise _busy_conflict("saving suggestions")
        state = libraries.read_workspace_state()
        existing_ids = {p.id for p in state.proposals}
        new_ones = [p for p in filtered if p.id not in existing_ids]
        if new_ones:
            state.proposals = [*state.proposals, *new_ones]
            libraries.write_workspace_state(state)
            libraries.reload()
        return _library_state_response(warning=warning)


@router.post("/api/libraries/proposals/approve", response_model=LibraryStateResponse)
def approve_library_proposals(body: ProposalApproveRequest) -> LibraryStateResponse:
    """Add selected pending proposals to the app-wide vocabulary.

    An alias goes to its proposed term (or `body.targets[id]`), creating that term when
    the dictionary lacks it. Nothing in the master resume changes: tags are stored as
    typed and canonicalised at match time, so there is no rewrite to confirm.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        state = libraries.read_workspace_state()
        wanted_ids = set(body.proposal_ids)
        selected = [p for p in state.proposals if p.id in wanted_ids]
        if not selected:
            raise HTTPException(status_code=404, detail="No matching pending proposals.")

        user = libraries.read_user_vocabulary()
        try:
            for p in selected:
                if p.kind == "tag_alias" and p.alias and p.canonical:
                    target = body.targets.get(p.id, "").strip() or p.canonical
                    user = libraries.add_alias(user, p.alias, target)
                elif p.kind == "verb_family" and p.verb and p.family:
                    user = libraries.add_verb(user, p.verb, p.family)
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        libraries.write_user_vocabulary(user)
        state.proposals = [p for p in state.proposals if p.id not in wanted_ids]
        libraries.write_workspace_state(state)
        libraries.reload()
        return _library_state_response()


@router.post("/api/libraries/proposals/reject", response_model=LibraryStateResponse)
def reject_library_proposals(body: ProposalRejectRequest) -> LibraryStateResponse:
    """Decline selected pending proposals so they are never re-proposed.

    Deliberately does not check `busy()` — unlike approve, rejecting changes nothing
    effective, so a running job must not block it (see
    `test_generate_and_reject_proceed_even_when_queue_busy`). It does still take
    `template_ops.LOCK` around the read-modify-write, matching every other route
    touching this same per-workspace state (including the job worker's own
    end-of-run proposal draft) — that's plain mutual exclusion, not a busy-based
    rejection, so it doesn't reintroduce the 409 that test guards against.
    """
    wanted_ids = set(body.proposal_ids)
    with template_ops.LOCK:
        state = libraries.read_workspace_state()
        selected = [p for p in state.proposals if p.id in wanted_ids]
        if not selected:
            return _library_state_response()

        existing_rejected = {
            (r.kind, r.alias, r.canonical, r.verb, r.family) for r in state.rejected
        }
        for p in selected:
            key = (p.kind, p.alias, p.canonical, p.verb, p.family)
            if key not in existing_rejected:
                state.rejected.append(
                    library_models.RejectedEntry(
                        kind=p.kind,
                        alias=p.alias,
                        canonical=p.canonical,
                        verb=p.verb,
                        family=p.family,
                    )
                )
                existing_rejected.add(key)
        state.proposals = [p for p in state.proposals if p.id not in wanted_ids]
        libraries.write_workspace_state(state)
        return _library_state_response()
