"""Vocabulary pack and proposal routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from resume_tailor import config
from resume_tailor.content import data, libraries, library_impact, library_models
from resume_tailor.pipeline import jd, propose
from resume_tailor.web import template_ops
from resume_tailor.web.jobs import get_queue
from resume_tailor.web.routes.resume import _backup_master_resume
from resume_tailor.web.routes.workspaces import _busy_conflict
from resume_tailor.web.schemas import (
    LibraryAliasImpactOut,
    LibraryEffectiveOut,
    LibraryImpactRequest,
    LibraryImpactResponse,
    LibraryOverridesOut,
    LibraryPackOut,
    LibraryPackSummaryOut,
    LibraryPackWriteRequest,
    LibraryProposalOut,
    LibrarySelectionRequest,
    LibraryStateResponse,
    ProposalApproveRequest,
    ProposalGenerateRequest,
    ProposalRejectRequest,
)

router = APIRouter()
_log = logging.getLogger(__name__)


def _library_pack_summary_out(pack: library_models.PackMeta) -> LibraryPackSummaryOut:
    return LibraryPackSummaryOut(
        id=pack.id,
        label=pack.label,
        description=pack.description,
        builtin=pack.builtin,
        customized=pack.customized,
        tag_alias_count=pack.tag_alias_count,
        verb_count=pack.verb_count,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


def _library_proposal_out(p: library_models.LibraryProposal) -> LibraryProposalOut:
    return LibraryProposalOut(
        id=p.id,
        kind=p.kind,
        alias=p.alias,
        canonical=p.canonical,
        verb=p.verb,
        family=p.family,
        rationale=p.rationale,
        source=p.source,
        created_at=p.created_at,
    )


def _library_state_response(*, warning: str | None = None) -> LibraryStateResponse:
    """Current pack list, active profile's selection/overrides/proposals, and the
    composed table's summary — the one payload every library route returns, so the
    Settings tab can re-render from a mutation's response instead of issuing a second
    fetch."""
    state = libraries.read_workspace_state()
    effective = libraries.resolve_effective()
    return LibraryStateResponse(
        packs=[_library_pack_summary_out(p) for p in libraries.list_packs()],
        enabled_packs=state.enabled_packs,
        overrides=LibraryOverridesOut(**state.overrides.model_dump()),
        effective=LibraryEffectiveOut(
            tag_alias_count=len(effective.tag_aliases),
            verb_count=len(effective.verb_index),
            fingerprint=libraries.effective_fingerprint(effective),
        ),
        diagnostics=effective.diagnostics,
        proposals=[_library_proposal_out(p) for p in state.proposals],
        warning=warning,
    )


def _library_pack_out(pack: library_models.Pack) -> LibraryPackOut:
    return LibraryPackOut(
        id=pack.id,
        label=pack.label,
        description=pack.description,
        builtin=libraries.is_builtin_pack(pack.id),
        customized=libraries.is_customized_pack(pack.id),
        tag_aliases=pack.tag_aliases,
        verb_families=pack.verb_families,
        created_at=pack.created_at,
        updated_at=pack.updated_at,
    )


@router.get("/api/libraries", response_model=LibraryStateResponse)
def get_libraries() -> LibraryStateResponse:
    """Every pack (built-in and user-authored), the active profile's selection and
    overrides, and the composed table's summary."""
    return _library_state_response()


@router.get("/api/libraries/packs/{pack_id}", response_model=LibraryPackOut)
def get_library_pack(pack_id: str) -> LibraryPackOut:
    """One pack's full contents, for the pack editor."""
    try:
        pack = libraries.read_pack(pack_id)
    except library_models.LibraryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _library_pack_out(pack)


def _library_write_conflict() -> HTTPException:
    return _busy_conflict("editing vocabulary packs")


@router.post("/api/libraries/packs", response_model=LibraryStateResponse)
def create_library_pack(body: LibraryPackWriteRequest) -> LibraryStateResponse:
    """Create a new user-authored pack. The id is derived from the label."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        existing_ids = {p.id for p in libraries.list_packs()}
        pack_id = libraries.new_pack_id(body.label, existing=existing_ids)
        pack = library_models.Pack(
            id=pack_id,
            label=body.label,
            description=body.description,
            tag_aliases=body.tag_aliases,
            verb_families=body.verb_families,
        )
        try:
            libraries.write_pack(pack, force=body.force)
        except library_models.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@router.put("/api/libraries/packs/{pack_id}", response_model=LibraryStateResponse)
def update_library_pack(pack_id: str, body: LibraryPackWriteRequest) -> LibraryStateResponse:
    """Update a pack's contents. Shipped ids write a shadow file over the bundled seed."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        pack = library_models.Pack(
            id=pack_id,
            label=body.label,
            description=body.description,
            tag_aliases=body.tag_aliases,
            verb_families=body.verb_families,
        )
        try:
            libraries.write_pack(pack, force=body.force)
        except library_models.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@router.delete("/api/libraries/packs/{pack_id}", response_model=LibraryStateResponse)
def delete_library_pack(pack_id: str) -> LibraryStateResponse:
    """Delete a user-authored pack. Refuses a shipped id.

    A profile that still has `pack_id` in its selection is left as-is —
    `libraries.resolve_effective` skips a missing pack with a diagnostic rather than
    erroring, so this cannot brick a profile that had it enabled.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        try:
            libraries.delete_pack(pack_id)
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@router.post("/api/libraries/packs/{pack_id}/reset", response_model=LibraryStateResponse)
def reset_library_pack(pack_id: str) -> LibraryStateResponse:
    """Restore a shipped pack to its bundled seed by deleting its shadow file."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        try:
            libraries.reset_pack(pack_id)
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        libraries.reload()
        return _library_state_response()


@router.put("/api/libraries/selection", response_model=LibraryStateResponse)
def put_library_selection(body: LibrarySelectionRequest) -> LibraryStateResponse:
    """Set the active profile's enabled packs and overrides."""
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        state = libraries.read_workspace_state()
        state.enabled_packs = body.enabled_packs
        state.overrides = library_models.LibraryOverrides(**body.overrides.model_dump())
        libraries.write_workspace_state(state)
        libraries.reload()
        return _library_state_response()


@router.post("/api/libraries/impact", response_model=LibraryImpactResponse)
def preview_library_impact(body: LibraryImpactRequest) -> LibraryImpactResponse:
    """What approving each of `tag_aliases` would rewrite in the current master
    resume, if anything — the confirmation step before a destructive alias write."""
    impacts = library_impact.alias_impact(body.tag_aliases)
    return LibraryImpactResponse(
        impacts=[
            LibraryAliasImpactOut(
                alias=i.alias,
                canonical=i.canonical,
                affected_tags=i.affected_tags,
                affected_bullets=i.affected_bullets,
            )
            for i in impacts
        ]
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
    (same as the import route's tag-suggestion pass), so this never silently falls
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
    """Fold selected pending proposals into an existing pack (user-authored or shipped).

    `Bullet._normalise_tags` re-canonicalises every tag on every master-resume save, so
    approving an alias whose key is already used as a literal bullet tag would silently
    rewrite it the next time the resume is saved. Refuses with 409 and the exact impact
    list unless `acknowledge_rewrites` is set, and takes a timestamped backup of the
    current master resume before writing whenever it is.
    """
    if get_queue().busy():
        raise _library_write_conflict()
    with template_ops.LOCK:
        state = libraries.read_workspace_state()
        wanted_ids = set(body.proposal_ids)
        selected = [p for p in state.proposals if p.id in wanted_ids]
        if not selected:
            raise HTTPException(status_code=404, detail="No matching pending proposals.")

        alias_map = {p.alias: p.canonical for p in selected if p.kind == "tag_alias" and p.alias}
        impacts = library_impact.alias_impact(alias_map) if alias_map else []
        rewriting = [i for i in impacts if i.affected_tags]
        if rewriting and not body.acknowledge_rewrites:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"Approving this rewrites {len(rewriting)} tag(s) already used "
                        f"in your master resume the next time it is saved."
                    ),
                    "impact": [
                        {
                            "alias": i.alias,
                            "canonical": i.canonical,
                            "affected_tags": i.affected_tags,
                            "affected_bullets": i.affected_bullets,
                        }
                        for i in rewriting
                    ],
                },
            )

        try:
            pack = libraries.read_pack(body.target_pack_id)
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if rewriting:
            _backup_master_resume(config.MASTER_RESUME_PATH)

        tag_aliases = dict(pack.tag_aliases)
        verb_families = {family: list(verbs) for family, verbs in pack.verb_families.items()}
        for p in selected:
            if p.kind == "tag_alias" and p.alias and p.canonical:
                tag_aliases[p.alias] = p.canonical
            elif p.kind == "verb_family" and p.verb and p.family:
                verbs = verb_families.setdefault(p.family, [])
                if p.verb not in verbs:
                    verbs.append(p.verb)

        updated = pack.model_copy(
            update={"tag_aliases": tag_aliases, "verb_families": verb_families}
        )
        try:
            libraries.write_pack(updated)
        except library_models.LibraryValidationError as exc:
            raise HTTPException(
                status_code=400, detail={"message": str(exc), "errors": exc.errors}
            ) from exc
        except library_models.LibraryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
