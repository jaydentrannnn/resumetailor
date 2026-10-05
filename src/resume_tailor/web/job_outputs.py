"""Converting pipeline results into API response schemas, and persisting the run record."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from resume_tailor.pipeline import (
    coverletter_models,
    expand,
    report,
    skills,
)
from resume_tailor.web.schemas import (
    CoverLetterOut,
    ExpandedEntryOut,
    ExpansionOut,
    KeywordGapOut,
    RunReportOut,
    SectionSummaryOut,
    SkillsPlanOut,
    SkillSuggestionOut,
)

from . import job_tailor_run, job_types


def _persist_run_record(job: job_types.Job, status: str | None = None) -> None:
    """Write `out_dir/run.json` so history and downloads survive a process restart.

    Called with the terminal status *before* it is published on `job.status`, so a
    client that sees the job finish can always find its record (succeeded / failed /
    cancelled). No-op when `out_dir` was never created (cancel-while-queued).
    """
    if job.out_dir is None:
        return
    title = job.report.title if job.report else job_tailor_run._jd_title_fallback(job.jd_text)
    record = {
        "job_id": job.job_id,
        "workspace_id": job.workspace_id,
        "created_at": job.created_at,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status or job.status,
        "title": title,
        "error": job.error,
        "report": job.report.model_dump() if job.report else None,
        "metadata": job.metadata.model_dump() if job.metadata else None,
        "guidance": ({
            "target_field": job.guidance.target_field,
            "version": job.guidance.version,
            "fingerprint": job.guidance.fingerprint(),
            "styles": {
                stage: "custom" if text is not None else "default"
                for stage, text in job.guidance.styles.items()
            },
        } if job.guidance else None),
    }
    try:
        job.out_dir.mkdir(parents=True, exist_ok=True)
        (job.out_dir / "run.json").write_text(
            json.dumps(record, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # Persistence is best-effort — a full disk must not turn a successful run into
        # a failed one after the .docx is already written.
        pass

def _to_expansion_out(expansion: expand.Expansion) -> ExpansionOut:
    """Convert the expand dataclass into the Pydantic shape the API serves."""
    return ExpansionOut(
        entries=[
            ExpandedEntryOut(
                entry_key=e.entry_key,
                title=e.title,
                company=e.company,
                location=e.location,
                start=e.start,
                end=e.end,
                bullets=list(e.bullets),
                char_count=e.char_count,
                warnings=list(e.warnings),
                on_resume=e.on_resume,
            )
            for e in expansion.entries
        ],
        warnings=list(expansion.warnings),
        model=expansion.model,
        char_limit=expansion.char_limit,
    )

def write_expansion(
    out_dir: Path, expansion: expand.Expansion, *, source_experience_count: int
) -> ExpansionOut:
    """Write `expansion.json`/`expansion.md` for a run and return the API shape.

    Shared by the tailoring run and on-demand generation so both leave identical files.
    `source_experience_count` is durable evidence that an empty expansion truly means
    there were no source jobs; later profile edits cannot establish this.
    """
    out = _to_expansion_out(expansion)
    record = out.model_dump()
    record["source_experience_count"] = source_experience_count
    (out_dir / "expansion.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (out_dir / "expansion.md").write_text(expand.format_markdown(expansion), encoding="utf-8")
    return out

def _to_skills_out(plan: skills.SkillsPlan) -> SkillsPlanOut:
    """Convert the skills dataclass into the Pydantic shape the API serves."""
    return SkillsPlanOut(
        skills=[
            SkillSuggestionOut(
                skill=s.skill,
                pool_label=s.pool_label,
                tier=s.tier,
                jd_phrase=s.jd_phrase,
                sources=list(s.sources),
                reason=s.reason,
            )
            for s in plan.skills
        ],
        warnings=list(plan.warnings),
        model=plan.model,
        pool_size=plan.pool_size,
    )

def _to_cover_out(
    letter: coverletter_models.CoverLetter,
    *,
    out_dir: Path | None = None,
) -> CoverLetterOut:
    """Convert the cover-letter dataclass into the Pydantic shape the API serves."""
    has_docx = False
    has_pdf = False
    if out_dir is not None:
        has_docx = (out_dir / "cover.docx").exists()
        has_pdf = (out_dir / "cover.pdf").exists()
    return CoverLetterOut(
        company=letter.company,
        company_location=letter.company_location,
        addressee=letter.addressee,
        paragraphs=list(letter.paragraphs),
        salutation=letter.salutation,
        closing=letter.closing,
        signature=letter.signature,
        inside_address=list(letter.inside_address),
        date=letter.date,
        warnings=list(letter.warnings),
        model=letter.model,
        word_count=letter.word_count,
        has_docx=has_docx,
        has_pdf=has_pdf,
    )

def _to_report_out(data: report.RunReport) -> RunReportOut:
    """Convert the dataclass report into the Pydantic shape the API serves."""
    return RunReportOut(
        title=data.title,
        seniority=data.seniority,
        coverage_matched=data.coverage_matched,
        coverage_total=data.coverage_total,
        extraction_diagnosis=data.extraction_diagnosis,
        missing_must_haves=data.missing_must_haves,
        unmatched_canonicals=[[c, p] for c, p in data.unmatched_canonicals],
        gaps=[
            KeywordGapOut(
                canonical=g.canonical,
                phrase=g.phrase,
                importance=g.importance,
                reason=g.reason,
                evidence=g.evidence,
                band=g.band,
                evidence_tier=g.evidence_tier,
            )
            for g in data.gaps
        ],
        model=data.model,
        semantic_used=data.semantic_used,
        bullets_selected=data.bullets_selected,
        bullets_total=data.bullets_total,
        experience=[
            SectionSummaryOut(label=s.label, kept=s.kept, total=s.total, rewritten=s.rewritten)
            for s in data.experience
        ],
        projects=[
            SectionSummaryOut(label=s.label, kept=s.kept, total=s.total, rewritten=s.rewritten)
            for s in data.projects
        ],
        dropped=data.dropped,
        pages=data.pages,
        pages_are_estimated=data.pages_are_estimated,
        iterations=data.iterations,
        widows_repaired=data.widows_repaired,
        widows_remaining=data.widows_remaining,
        verbs_diversified=data.verbs_diversified,
        verb_collisions_remaining=data.verb_collisions_remaining,
        warnings=data.warnings,
        out_path=data.out_path,
        pdf_backend=data.pdf_backend,
        calibration_source=data.calibration_source,
        calibration_rejection=data.calibration_rejection,
        topped_up=data.topped_up,
        fit_trace=data.fit_trace,
        quality=data.quality,
    )
