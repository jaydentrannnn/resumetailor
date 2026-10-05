"""LLM operations around a finished run: vocabulary proposals, cover letters, claim checks."""

from __future__ import annotations

import json
from dataclasses import replace

from resume_tailor import config
from resume_tailor.content import data, industries, libraries, style
from resume_tailor.content.data import MasterResume
from resume_tailor.pipeline import (
    bullet_checks,
    coverletter,
    coverletter_format,
    coverletter_models,
    expand,
    jd,
    propose,
    relevance,
)
from resume_tailor.pipeline.events import ProgressCallback, ProgressEvent
from resume_tailor.web import template_ops
from resume_tailor.web.schemas import (
    CoverAnglesIn,
    CoverLetterOut,
    ExpansionOut,
)

from . import job_outputs


def _draft_vocabulary_proposals(
    *,
    known_tags: list[str],
    master_resume: MasterResume,
    requirements: jd.JobRequirements,
    selected_texts: dict[str, str],
    on_event: ProgressCallback,
) -> None:
    """Opportunistic, opt-in vocabulary-proposal draft for the active profile, run at
    the end of a successful job (`settings.suggest_vocabulary`).

    Fed by this run's own near-miss keyword gaps and unclassified opening verbs among
    the bullets actually selected — the same signals a user would eyeball in the report,
    turned into a queued suggestion instead. Non-fatal by construction: the caller wraps
    this in a bare `except Exception`, since a run whose `.docx` already succeeded must
    never fail over an advisory feature.
    """
    unmatched = propose.near_miss_alias_candidates(requirements, master_resume)
    unknown_verbs = sorted(
        {
            verb
            for text in selected_texts.values()
            if (verb := bullet_checks.opening_verb(text)) and config.verb_family(verb) is None
        }
    )
    if not unmatched and not unknown_verbs:
        return

    effective = libraries.resolve_effective()
    state = libraries.read_workspace_state()
    raw = propose.propose_vocabulary(
        known_tags=known_tags,
        unmatched=unmatched,
        unknown_verbs=unknown_verbs,
        families=effective.verb_families,
        on_event=on_event,
    )
    filtered = propose.filter_proposals(
        raw,
        known_tags=known_tags,
        effective=effective,
        rejected=state.rejected,
        source="run",
    )
    if not filtered:
        return

    # The read-modify-write of `state.proposals` is held under `template_ops.LOCK` —
    # the Settings tab's approve/reject routes do the same wholesale
    # read-modify-write of libraries.json with no lock of their own otherwise, so
    # whichever side runs second silently loses the other's change. `state` itself
    # (read above, before `propose_vocabulary`'s LLM call) is deliberately *not* what
    # gets written: re-reading here means a concurrent approve/reject that landed
    # while that call was in flight isn't clobbered by a write based on stale data.
    with template_ops.LOCK:
        fresh_state = libraries.read_workspace_state()
        # filter_proposals already excludes anything in `state.rejected` as of the read
        # above; this only needs to dedupe against proposals already pending, which it
        # had no visibility into.
        existing_ids = {p.id for p in fresh_state.proposals}
        new_ones = [p for p in filtered if p.id not in existing_ids]
        if not new_ones:
            return
        fresh_state.proposals = [*fresh_state.proposals, *new_ones]
        libraries.write_workspace_state(fresh_state)
        libraries.reload()
    on_event(
        ProgressEvent(
            stage="propose",
            message=f"Drafted {len(new_ones)} vocabulary suggestion(s) for review in Settings",
            detail={"count": len(new_ones)},
        )
    )

def regenerate_cover_letter(
    job_id: str,
    *,
    instruction: str = "",
    cover_angles: CoverAnglesIn | None = None,
) -> CoverLetterOut:
    """Re-draft and re-render a job's cover letter, overwriting artifacts in place."""
    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    bullets_path = out_dir / "bullets.json"
    backends_path = out_dir / "backends.json"
    if not bullets_path.exists():
        raise FileNotFoundError("This job has no saved tailored bullets for regeneration.")

    bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
    backend_specs = json.loads(backends_path.read_text(encoding="utf-8"))
    jd_path = out_dir / "jd.txt"
    if not jd_path.exists():
        raise FileNotFoundError("This job has no saved job description.")
    jd_text = jd_path.read_text(encoding="utf-8")

    requirements_path = out_dir / "requirements.json"
    if not requirements_path.exists():
        raise FileNotFoundError("This job has no saved requirements.")
    requirements = jd.JobRequirements.model_validate_json(
        requirements_path.read_text(encoding="utf-8")
    )

    angles = None
    if cover_angles is not None:
        angles = coverletter_models.CoverAngles(
            why_company=cover_angles.why_company,
            problem=cover_angles.problem,
            approach=cover_angles.approach,
            tone=cover_angles.tone,
        )

    snapshot = industries.load(out_dir)
    workspace_id = config.active_workspace_id()
    context = (
        config.context_for_workspace(workspace_id)
        if workspace_id is not None else config.default_context()
    )
    with config.use_context(replace(context, guidance=snapshot)), \
            config.pinned_specs(backend_specs, effort=None):
        industries.bind(snapshot)
        if snapshot is not None:
            style.activate(**snapshot.styles)
        resume = data.load()
        letter = coverletter.draft_letter(
            resume,
            requirements,
            bullets,
            jd_text,
            use_cache=False,
            instruction=instruction,
            angles=angles,
        )
        coverletter.render_cover_letter(resume, letter, out=out_dir / "cover.docx")

    out = job_outputs._to_cover_out(letter, out_dir=out_dir)
    (out_dir / "cover.json").write_text(out.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "cover.md").write_text(
        coverletter_format.format_markdown(letter),
        encoding="utf-8",
    )
    return out

def generate_expansion(job_id: str) -> ExpansionOut:
    """Write a finished run's experience expansion now, from its saved inputs.

    Runs skip expansion unless Apply needs it (`JobSettings.no_expand` defaults on); this
    is the on-demand path — the job page's Generate button and Apply's Prepare when a
    run is missing only its expansion. Same inputs as the in-run stage: the requirements
    and bullets the run saved, the unfiltered master resume, and the run's relevance
    scores (usually a cache hit). One expand call; nothing else is re-run.
    """
    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    names = ("requirements.json", "bullets.json", "backends.json")
    paths = {name: out_dir / name for name in names}
    for name, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"This job has no saved {name.removesuffix('.json')}.")
    requirements = jd.JobRequirements.model_validate_json(
        paths["requirements.json"].read_text(encoding="utf-8")
    )
    bullets = json.loads(paths["bullets.json"].read_text(encoding="utf-8"))
    backend_specs = json.loads(paths["backends.json"].read_text(encoding="utf-8"))

    snapshot = industries.load(out_dir)
    workspace_id = config.active_workspace_id()
    context = (
        config.context_for_workspace(workspace_id)
        if workspace_id is not None else config.default_context()
    )
    with config.use_context(replace(context, guidance=snapshot)), \
            config.pinned_specs(backend_specs, effort=None):
        industries.bind(snapshot)
        if snapshot is not None:
            style.activate(**snapshot.styles)
        resume = data.load()
        try:
            semantic = relevance.score_table(resume.all_bullets(), requirements, use_cache=True)
        except Exception:  # noqa: BLE001 - ranking falls back to keywords, as in a run
            semantic = None
        expansion = expand.expand_experience(
            resume,
            requirements,
            resume_bullet_ids=set(bullets),
            semantic=semantic,
            use_cache=True,
        )
    out = job_outputs.write_expansion(
        out_dir, expansion, source_experience_count=len(resume.experience)
    )
    if (out_dir / "packet.json").is_file():
        # The application kit embeds the expansion and its hash; rebuild it so Fill
        # pastes the new text.
        from resume_tailor.apply.funnel import packet as apply_packet

        apply_packet.write_packet(job_id)
    return out

def verify_claim(job_id: str | None, text: str) -> coverletter.ClaimCheck:
    """Check free-text application prose against tailored or master-resume bullets.

    When ``job_id`` is set, reloads ``bullets.json`` and ``jd.txt`` from the job
    directory (same artifacts ``regenerate_cover_letter`` uses). When omitted,
    checks against every bullet in the master resume with an empty JD context.
    Pure — no LLM, no disk writes. Raises ``FileNotFoundError`` when a job-scoped
    run has no saved bullets or JD.
    """
    resume = data.load()
    if job_id is None:
        bullets = {bullet.id: bullet.text for bullet in resume.all_bullets()}
        return coverletter.check_claims(resume, bullets, "", text)

    out_dir = config.OUTPUT_DIR / "jobs" / job_id
    bullets_path = out_dir / "bullets.json"
    if not bullets_path.exists():
        raise FileNotFoundError(
            "This job has no saved tailored bullets for claim verification."
        )
    jd_path = out_dir / "jd.txt"
    if not jd_path.exists():
        raise FileNotFoundError("This job has no saved job description.")

    bullets = json.loads(bullets_path.read_text(encoding="utf-8"))
    jd_text = jd_path.read_text(encoding="utf-8")
    return coverletter.check_claims(resume, bullets, jd_text, text)
