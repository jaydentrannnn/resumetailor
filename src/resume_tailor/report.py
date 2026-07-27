"""Human-readable summary of a tailoring run.

Pure formatting over already-computed results: no API calls, no document access. Kept
separate from `tailor.py` so the summary can be asserted in tests without going through
`argparse` and `sys.stdout`.

What it answers, in the order a user actually asks it:
  - Is this posting even a good fit? (must-have keyword coverage)
  - What did the tool change, and where? (rewrites per section)
  - Did it have to fight to fit? (iterations, final page count)
  - Where is the file?
"""

from __future__ import annotations

from dataclasses import dataclass

from . import config
from .data import Experience, MasterResume, Project
from .fit import FitResult
from .jd import JobRequirements
from .rewrite import keyword_coverage


@dataclass
class SectionSummary:
    """How much of one experience/project entry survived into the final document."""

    label: str
    kept: int
    total: int
    rewritten: int


def _entry_name(entry: Experience | Project) -> str:
    return entry.company if isinstance(entry, Experience) else entry.name


def _summarise(
    entries: list[Experience] | list[Project], result: FitResult
) -> list[SectionSummary]:
    absorbed = {mid for m in result.merges for mid in m.member_ids[1:]}
    summaries: list[SectionSummary] = []
    for entry in entries:
        kept = [b for b in entry.bullets if b.id in result.bullets or b.id in absorbed]
        if not kept:
            continue
        # A bullet counts as rewritten only if its text actually changed; absorbed
        # members are also "rewritten" because they cease to render under their own ids.
        rewritten = 0
        for b in kept:
            if b.id in absorbed:
                rewritten += 1
            else:
                rewritten += 1 if result.bullets[b.id].strip() != b.text.strip() else 0
        summaries.append(
            SectionSummary(
                label=_entry_name(entry),
                kept=len(kept),
                total=len(entry.bullets),
                rewritten=rewritten,
            )
        )
    return summaries


def missing_must_haves(requirements: JobRequirements, resume: MasterResume) -> list[str]:
    """Must-have keywords the master resume cannot support at all.

    Surfaced rather than hidden: these are the gaps no amount of rewriting can close, and
    the honest answer is that the candidate does not have that experience.
    """
    available = {t for b in resume.all_bullets() for t in b.tags}
    return [
        kw.phrase for kw in requirements.by_importance("must_have") if kw.canonical not in available
    ]


def unmatched_canonicals(
    requirements: JobRequirements, resume: MasterResume
) -> list[tuple[str, str]]:
    """Every keyword whose canonical matches no tag, as (canonical, phrase) pairs.

    Distinct from `missing_must_haves` in two ways: it covers nice-to-haves as well, and it
    reports the *canonical* rather than the posting's phrasing, because the canonical is what
    actually failed to match.

    Worth printing because a miss here is otherwise completely silent — scoring is exact set
    membership, so an unmatched canonical contributes nothing and says nothing. Now that
    extraction canonicalises against the resume's own vocabulary, a miss is meaningful: it
    means the resume genuinely lacks that skill rather than merely spelling it differently.
    A run showing many unmatched canonicals is a signal to check the master resume's tags,
    or to conclude the posting is a poor fit.
    """
    available = {t for b in resume.all_bullets() for t in b.tags}
    seen: dict[str, str] = {}
    for kw in requirements.keywords:
        if kw.canonical not in available:
            seen.setdefault(kw.canonical, kw.phrase)
    return sorted(seen.items())


def backends_used() -> str:
    """One line naming the model behind each stage.

    Printed on every run because with several backends selectable, "which model wrote this
    resume" has to be answerable from the output rather than inferred from which flag the
    user believes they passed. Collapses to a single name when one model served everything,
    which is the common case.
    """
    labels = {p: config.backend_for(p).label() for p in config.PURPOSES}
    distinct = set(labels.values())
    if len(distinct) == 1:
        return distinct.pop()
    return ", ".join(f"{purpose}={labels[purpose]}" for purpose in config.PURPOSES)


@dataclass
class RunReport:
    """The end-of-run summary as data, for callers that render it themselves.

    Same content as `format_report`, minus the formatting. Exists because the web UI needs
    the numbers separately to lay them out — scraping them back out of the text report
    would couple the UI to prose that is written for a terminal.
    """

    title: str
    seniority: str

    #: Must-have keywords the resume can support, out of all must-haves in the posting.
    coverage_matched: int
    coverage_total: int

    #: Must-haves no bullet is tagged for: the gaps rewriting cannot close.
    missing_must_haves: list[str]

    #: (canonical, phrase) for every keyword — must-have or not — matching no tag.
    unmatched_canonicals: list[tuple[str, str]]

    model: str
    semantic_used: bool

    bullets_selected: int
    bullets_total: int
    experience: list[SectionSummary]
    projects: list[SectionSummary]
    dropped: list[str]

    pages: int
    pages_are_estimated: bool
    iterations: int
    widows_repaired: int
    widows_remaining: int

    warnings: list[str]
    out_path: str

    #: Which engine measured the pages, and whether its fit constants were measured or
    #: inherited. Surfaced because inheriting Word's constants under LibreOffice sizes
    #: every page slightly wrong, and nothing else in the output would reveal it.
    pdf_backend: str
    calibration_source: str


def report_data(
    resume: MasterResume, requirements: JobRequirements, result: FitResult
) -> RunReport:
    """Assemble the run summary as structured data."""
    matched, total = keyword_coverage(requirements, resume)
    return RunReport(
        title=requirements.title,
        seniority=requirements.seniority,
        coverage_matched=matched,
        coverage_total=total,
        missing_must_haves=missing_must_haves(requirements, resume),
        unmatched_canonicals=unmatched_canonicals(requirements, resume),
        model=backends_used(),
        semantic_used=result.semantic_used,
        bullets_selected=result.bullets_selected,
        bullets_total=result.bullets_total,
        experience=_summarise(resume.experience, result),
        projects=_summarise(resume.projects, result),
        dropped=[
            _entry_name(e)
            for e in [*resume.experience, *resume.projects]
            if e.bullets and not any(b.id in result.bullets for b in e.bullets)
        ],
        pages=result.pages,
        pages_are_estimated=result.pages_are_estimated,
        iterations=result.iterations,
        widows_repaired=result.widows_repaired,
        widows_remaining=result.widows_remaining,
        warnings=list(result.warnings),
        out_path=str(result.out_path),
        pdf_backend=config.PDF_BACKEND,
        calibration_source=config.CALIBRATION_SOURCE,
    )


def format_report(
    resume: MasterResume, requirements: JobRequirements, result: FitResult
) -> str:
    """Render the end-of-run summary as plain text."""
    matched, total = keyword_coverage(requirements, resume)
    pct = f"{matched / total:.0%}" if total else "n/a"

    lines: list[str] = [
        f"Tailored for: {requirements.title} ({requirements.seniority})",
        "",
        f"Must-have keyword coverage: {matched}/{total} ({pct})",
    ]

    missing = missing_must_haves(requirements, resume)
    if missing:
        lines.append(f"  Not supported by the master resume: {', '.join(missing)}")

    unmatched = unmatched_canonicals(requirements, resume)
    if unmatched:
        lines.append(
            f"  Matched no tag ({len(unmatched)} of {len(requirements.keywords)} keywords): "
            + ", ".join(canonical for canonical, _ in unmatched)
        )

    ranking = "keyword overlap + semantic relevance" if result.semantic_used else "keyword overlap only"
    lines += [
        "",
        f"Model: {backends_used()}",
        f"Ranking: {ranking}",
        f"Bullets: {result.bullets_selected} of {result.bullets_total} selected",
    ]

    for title, entries in (
        ("Experience", resume.experience),
        ("Projects", resume.projects),
    ):
        summaries = _summarise(entries, result)
        if not summaries:
            continue
        lines.append(f"  {title}: {len(summaries)} of {len(entries)} entries")
        for s in summaries:
            lines.append(
                f"    {s.label}: {s.kept}/{s.total} bullets, {s.rewritten} rewritten"
            )

    dropped = [
        _entry_name(e)
        for e in [*resume.experience, *resume.projects]
        if e.bullets and not any(b.id in result.bullets for b in e.bullets)
    ]
    if dropped:
        lines.append(f"  Dropped entirely: {', '.join(dropped)}")

    if result.merges:
        lines.append("")
        lines.append(f"Merges: {len(result.merges)} accepted")
        for m in result.merges:
            members = " + ".join(m.member_ids)
            lines.append(f"  - {members} -> {m.survivor_id} (affinity={m.affinity:.2f})")
            if m.reason:
                lines.append(f"    {m.reason}")

    page_note = " (estimated — Word unavailable)" if result.pages_are_estimated else ""
    lines += [
        "",
        f"Fit: {result.pages} page(s){page_note} in {result.iterations} iteration(s)",
    ]

    # Worth its own line because a wasted line is invisible in a page count: a resume can
    # hit its page target while throwing away several lines to bullets that wrapped onto a
    # final line holding one word.
    tightened = (
        f" ({result.widows_repaired} bullet(s) tightened)" if result.widows_repaired else ""
    )
    lines.append(f"Line waste: {result.widows_remaining} widowed line(s){tightened}")

    lines.append(f"Output: {result.out_path}")

    for warning in result.warnings:
        lines.append(f"WARNING: {warning}")

    return "\n".join(lines)
