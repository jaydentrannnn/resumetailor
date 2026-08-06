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

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from . import config
from .data import Experience, MasterResume, Project
from .facets import labels_are_equivalent
from .fit import FitResult
from .jd import JobRequirements
from .rewrite import keyword_coverage

if TYPE_CHECKING:
    from .expand import Expansion

#: Characters Windows (and most filesystems) reject in a filename.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class SectionSummary:
    """How much of one experience/project entry survived into the final document.

    Named for historical reasons (it predates `MasterResume.sections`) — despite the
    name, one instance covers one *entry*, not one section. `RunReportSection` below is
    the actual per-section grouping.
    """

    label: str
    kept: int
    total: int
    rewritten: int


@dataclass
class RunReportSection:
    """One resume section's worth of entry summaries, in section order."""

    id: str
    title: str
    kind: str
    entries: list[SectionSummary]


def _entry_name(entry: Experience | Project) -> str:
    return entry.company if isinstance(entry, Experience) else entry.name


def _safe_filename_part(text: str) -> str:
    """Strip characters that cannot appear in a cross-platform filename."""
    cleaned = _UNSAFE_FILENAME.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "untitled"


def export_filename(name: str, title: str, *, suffix: str = ".docx") -> str:
    """Build the user-facing export name: ``<name> Resume - <title><suffix>``.

    Used for both the CLI default ``--out`` path and the download
    ``Content-Disposition`` filename. On-disk job artifacts may still use a
    stable internal name; this is what the applicant sees when saving the file.
    """
    stem = f"{_safe_filename_part(name)} Resume - {_safe_filename_part(title)}"
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{stem}{suffix}"


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


@dataclass
class KeywordGap:
    """Why one unmatched must-have missed, and what (if anything) to do about it.

    `missing_must_haves` and `unmatched_canonicals` say *that* a keyword matched no bullet
    tag; they cannot say why, and "you've never touched TensorFlow" and "PyTorch is in your
    project tech array but no bullet is tagged for it" call for opposite actions. This is
    the diagnosis that tells them apart.
    """

    canonical: str
    #: The JD's own wording — what to paste into the tag editor.
    phrase: str
    importance: str
    #: "near_miss": a bullet tag names the same thing under a different spelling.
    #: "untagged_evidence": the tech/skills/coursework pools have it, but no bullet tag does.
    #: "no_evidence": nothing in the master resume supports it.
    reason: Literal["no_evidence", "untagged_evidence", "near_miss"]
    evidence: list[str]


def diagnose_gaps(requirements: JobRequirements, master: MasterResume) -> list[KeywordGap]:
    """Explain every unmatched keyword instead of just naming it.

    Takes `master` — the *pre-facets* resume — deliberately, not whatever resume a caller
    happens to have in scope. `facets.apply` truncates `Project.tech` to its ≤4-label
    render budget, so a resume already run through facets can easily be missing the exact
    evidence this function exists to find (see the `master=` parameter on `report_data` /
    `format_report`, added for the same reason).

    Reuses `facets.labels_are_equivalent` for the near-miss and untagged-evidence checks
    rather than a second string-similarity implementation: it already carries the acronym
    ladder, alphanumeric-prefix containment, token-set containment, and word-by-word
    acronym alignment, each added for a live rename failure. It catches *spelling*
    variance only — it does not relate `aws` to `cloud computing`, or `distributed
    training` to `multi-machine setups` (both verified `no_evidence`). That conceptual
    relatedness is `SEMANTIC_WEIGHT`'s job for ranking; hand-rolling a hyponym table here
    would recreate `TAG_ALIASES`'s own documented failure mode in a second place.

    Does not consult `tag_vocabulary`: the editor keeps it set-identical to the bullet-tag
    set, so it can only ever duplicate a `near_miss` this function already finds via tags.
    """
    bullet_tags = sorted({t for b in master.all_bullets() for t in b.tags})
    unmatched = unmatched_canonicals(requirements, master)
    if not unmatched:
        return []

    phrase_by_canonical = {kw.canonical: kw.phrase for kw in requirements.keywords}
    importance_by_canonical = {kw.canonical: kw.importance for kw in requirements.keywords}

    gaps: list[KeywordGap] = []
    for canonical, _phrase in unmatched:
        phrase = phrase_by_canonical.get(canonical, canonical)
        importance = importance_by_canonical.get(canonical, "nice_to_have")

        near_miss = next(
            (tag for tag in bullet_tags if labels_are_equivalent(canonical, tag)), None
        )
        if near_miss is not None:
            gaps.append(
                KeywordGap(
                    canonical=canonical,
                    phrase=phrase,
                    importance=importance,
                    reason="near_miss",
                    evidence=[f'bullet tag: "{near_miss}"'],
                )
            )
            continue

        evidence: list[str] = []
        for proj in master.projects:
            for tech in proj.tech:
                if labels_are_equivalent(canonical, tech):
                    evidence.append(f'project tech {proj.id!r}: "{tech}"')
        for group in master.skills:
            for item in group.items:
                if labels_are_equivalent(canonical, item):
                    evidence.append(f'skills {group.label!r}: "{item}"')
        for edu in master.education:
            for course in edu.coursework:
                if labels_are_equivalent(canonical, course):
                    evidence.append(f'coursework: "{course}"')

        if evidence:
            gaps.append(
                KeywordGap(
                    canonical=canonical,
                    phrase=phrase,
                    importance=importance,
                    reason="untagged_evidence",
                    evidence=evidence,
                )
            )
        else:
            gaps.append(
                KeywordGap(
                    canonical=canonical,
                    phrase=phrase,
                    importance=importance,
                    reason="no_evidence",
                    evidence=[],
                )
            )
    return gaps


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

    #: Why each unmatched keyword missed, and what evidence (if any) supports it elsewhere
    #: in the master resume. See `diagnose_gaps`.
    gaps: list[KeywordGap]

    model: str
    semantic_used: bool

    bullets_selected: int
    bullets_total: int
    experience: list[SectionSummary]
    projects: list[SectionSummary]
    #: Every entry section (any kind, any count), in resume order — the general form of
    #: `experience`/`projects` above, which stay as flattened two-section views for
    #: existing callers.
    sections: list[RunReportSection]
    dropped: list[str]

    pages: int
    pages_are_estimated: bool
    iterations: int
    widows_repaired: int
    widows_remaining: int

    #: Opening verbs the polish pass replaced, and repeats it could not resolve.
    verbs_diversified: int
    verb_collisions_remaining: int

    warnings: list[str]
    out_path: str

    #: Which engine measured the pages, and whether its fit constants were measured or
    #: inherited. Surfaced because inheriting Word's constants under LibreOffice sizes
    #: every page slightly wrong, and nothing else in the output would reveal it.
    pdf_backend: str
    calibration_source: str
    #: Non-None when a calibration file existed but was rejected as implausible (see
    #: `config.PLAUSIBLE_CHARS_PER_LINE`) rather than simply absent — both cases leave
    #: `calibration_source == "fallback"`, so this is the only way to tell them apart.
    calibration_rejection: str | None = None


def report_data(
    resume: MasterResume,
    requirements: JobRequirements,
    result: FitResult,
    *,
    master: MasterResume | None = None,
) -> RunReport:
    """Assemble the run summary as structured data.

    `master` should be the *pre-facets* resume, for `diagnose_gaps` — see its docstring
    for why. Defaults to `resume` so every existing 3-argument call site (and every test
    that predates this parameter) keeps working unchanged.
    """
    master = master or resume
    matched, total = keyword_coverage(requirements, resume)
    return RunReport(
        title=requirements.title,
        seniority=requirements.seniority,
        coverage_matched=matched,
        coverage_total=total,
        missing_must_haves=missing_must_haves(requirements, resume),
        unmatched_canonicals=unmatched_canonicals(requirements, resume),
        gaps=diagnose_gaps(requirements, master),
        model=backends_used(),
        semantic_used=result.semantic_used,
        bullets_selected=result.bullets_selected,
        bullets_total=result.bullets_total,
        experience=_summarise(resume.experience, result),
        projects=_summarise(resume.projects, result),
        sections=[
            RunReportSection(
                id=section.id,
                title=section.title,
                kind=section.kind,
                entries=_summarise(section.entries, result),
            )
            for section in resume.entry_sections
        ],
        dropped=[
            _entry_name(e)
            for section in resume.entry_sections
            for e in section.entries
            if e.bullets and not any(b.id in result.bullets for b in e.bullets)
        ],
        pages=result.pages,
        pages_are_estimated=result.pages_are_estimated,
        iterations=result.iterations,
        widows_repaired=result.widows_repaired,
        widows_remaining=result.widows_remaining,
        verbs_diversified=result.verbs_diversified,
        verb_collisions_remaining=result.verb_collisions_remaining,
        warnings=list(result.warnings),
        out_path=str(result.out_path),
        pdf_backend=config.PDF_BACKEND,
        calibration_source=config.CALIBRATION_SOURCE,
        calibration_rejection=config.CALIBRATION_REJECTION,
    )


def format_report(
    resume: MasterResume,
    requirements: JobRequirements,
    result: FitResult,
    *,
    master: MasterResume | None = None,
) -> str:
    """Render the end-of-run summary as plain text.

    `master` should be the *pre-facets* resume — see `report_data`'s docstring; defaults
    to `resume` so every existing 3-argument call site keeps working unchanged.
    """
    master = master or resume
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

    gaps = diagnose_gaps(requirements, master)
    no_evidence = [g for g in gaps if g.reason == "no_evidence"]
    untagged = [g for g in gaps if g.reason == "untagged_evidence"]
    near_miss = [g for g in gaps if g.reason == "near_miss"]
    if no_evidence:
        lines.append(
            "  No evidence in the master resume: "
            + ", ".join(g.phrase for g in no_evidence)
        )
    if untagged:
        lines.append("  Evidence exists but no bullet is tagged for it:")
        for g in untagged:
            lines.append(f"    {g.phrase} <- {'; '.join(g.evidence)}")
    if near_miss:
        lines.append("  Tagged under a different name:")
        for g in near_miss:
            lines.append(f"    {g.phrase} <- {'; '.join(g.evidence)}")

    ranking = "keyword overlap + semantic relevance" if result.semantic_used else "keyword overlap only"
    lines += [
        "",
        f"Model: {backends_used()}",
        f"Ranking: {ranking}",
        f"Bullets: {result.bullets_selected} of {result.bullets_total} selected",
    ]

    for section in resume.entry_sections:
        summaries = _summarise(section.entries, result)
        if not summaries:
            continue
        lines.append(f"  {section.title}: {len(summaries)} of {len(section.entries)} entries")
        for s in summaries:
            lines.append(
                f"    {s.label}: {s.kept}/{s.total} bullets, {s.rewritten} rewritten"
            )

    dropped = [
        _entry_name(e)
        for section in resume.entry_sections
        for e in section.entries
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

    # Costs no space, so it needs its own line for the same reason: a resume can hit every
    # numeric target and still open half its bullets with the same verb.
    revoiced = (
        f" ({result.verbs_diversified} verb(s) replaced)" if result.verbs_diversified else ""
    )
    lines.append(f"Verb variety: {result.verb_collisions_remaining} repeated opener(s){revoiced}")

    lines.append(f"Output: {result.out_path}")

    for warning in result.warnings:
        lines.append(f"WARNING: {warning}")

    return "\n".join(lines)


def format_expansion(expansion: Expansion) -> str:
    """Render the application-form experience expansion for the terminal.

    Kept separate from `format_report` because expansion succeeds or fails independently
    of the fit loop, and the CLI prints it only when the call ran.
    """
    from . import expand as expand_mod

    lines: list[str] = [
        f"Application experience ({len(expansion.entries)} entr"
        f"{'y' if len(expansion.entries) == 1 else 'ies'}, model={expansion.model}, "
        f"limit={expansion.char_limit} chars/entry):",
    ]
    for entry in expansion.entries:
        flag = " [on resume]" if entry.on_resume else ""
        lines.append(
            f"  {entry.title} @ {entry.company}{flag} "
            f"({entry.char_count}/{expansion.char_limit} chars, {len(entry.bullets)} bullets)"
        )
        for warning in entry.warnings:
            lines.append(f"    warning: {warning}")
    for warning in expansion.warnings:
        lines.append(f"  WARNING: {warning}")
    if expansion.entries:
        lines.append("")
        lines.append(expand_mod.format_markdown(expansion))
    return "\n".join(lines)
