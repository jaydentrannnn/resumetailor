"""Line estimates for a draft: per-bullet, per-entry and per-section lines, and widows."""

from __future__ import annotations

import math
from pathlib import Path

from .. import config
from ..content.data import Bullet, Experience, MasterResume, Project
from ..document import render
from ..document.template_profile import active_layout
from . import fit_types


def _widow_fits(
    path: Path, texts: dict[str, str], *, estimated: bool
) -> tuple[dict[str, render.LineFit], set[str]]:
    measured: dict[str, render.LineFit] = {}
    pdf = path.with_suffix(".pdf")
    if not estimated and pdf.exists():
        measured = render.line_layout(pdf, texts)
    measured_ids = set(measured)
    for bid, text in texts.items():
        if bid not in measured:
            measured[bid] = render.LineFit(
                config.line_span(text),
                config.last_line_fill(text) / config.CHARS_PER_LINE,
                float(config.CHARS_PER_LINE),
            )
    return measured, measured_ids

def _widow_targets(
    texts: dict[str, str], sources: dict[str, Bullet],
    layout: dict[str, render.LineFit], *, measured_lines: int, capacity: int,
    members: dict[str, tuple[str, ...]], estimated: bool,
    measured_ids: set[str] | None = None,
) -> dict[str, tuple[int, int]]:
    targets: dict[str, tuple[int, int]] = {}
    measured_ids = measured_ids if measured_ids is not None else set(layout)
    for bid, text in texts.items():
        fit = layout[bid]
        floor = (config.WIDOW_MIN_FILL if not estimated and bid in measured_ids
                 else config.WIDOW_EST_FILL)
        if fit.lines <= 1 or fit.last_fill >= floor or bid not in sources:
            continue
        span = fit.chars_per_line
        if fit.last_fill <= config.WIDOW_SHORTEN_MAX or measured_lines >= capacity or bid in members:
            high = int((fit.lines - 1) * span - config.WIDOW_SAFETY)
            if high >= 1:
                targets[bid] = (0, high)
        elif len(sources[bid].text) > len(text):
            low = math.ceil(
                len(text) + (config.WIDOW_EXTEND_FILL - fit.last_fill) * span - 1e-9
            )
            high = int(fit.lines * span - config.WIDOW_SAFETY)
            if low <= high:
                targets[bid] = (low, high)
    return targets

def _line_saving_ceilings(
    targets: dict[str, tuple[int, int]], layout: dict[str, render.LineFit]
) -> dict[str, int]:
    """For EXTEND targets, the length at which a draft instead saves the whole last line.

    A draft that misses the extend window by coming back a full line shorter also cures
    the widow, so `_polish` accepts either rather than asking the model to hit one narrow
    window exactly."""
    ceilings: dict[str, int] = {}
    for bid, (low, _high) in targets.items():
        if low <= 0:
            continue
        fit = layout[bid]
        ceiling = int((fit.lines - 1) * fit.chars_per_line - config.WIDOW_SAFETY)
        if ceiling >= 1:
            ceilings[bid] = ceiling
    return ceilings

# --------------------------------------------------------------------------------------
# Budget estimation — cheap, no LLM, no render. Mirrors build_context's own filtering
# rules so the estimate and the real render always agree on which entries survive.
# --------------------------------------------------------------------------------------
def _bullet_lines(text: str) -> int:
    """Delegated so the budget estimator and the widow detector cannot disagree.

    Both answer "how many lines is this text?" — if they ever computed it differently, the
    loop would be sizing pages against one definition while `bullet_checks.widowed` trimmed
    against another.
    """
    return config.line_span(text)

def _fixed_overhead_lines(resume: MasterResume, *, layout: dict | None = None) -> int:
    """Lines that render regardless of selection: header, contact, education, skills.

    Education and skills never vary by posting, but their line *count* still depends on
    the master resume's own content (coursework wrap, GPA suffix, skill group length),
    so it is measured from `resume` rather than hard-coded. Sections disabled in the
    active template profile contribute zero.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {}

    lines = 2  # name line + contact line
    if enabled.get("education", True):
        lines += 1  # section header
        for edu in resume.education:
            lines += 1  # school | location ... dates
            lines += _bullet_lines(render._degree_line(edu))
            for detail in render._education_details(edu):
                lines += _bullet_lines(detail)

    if enabled.get("skills", True) and resume.skills:
        lines += 1  # section header
        for group in resume.skills:
            lines += _bullet_lines(config.skill_group_line(group.label, group.items))
    return lines

def _entry_lines(entry: Experience | Project, bullets: dict[str, str]) -> int:
    kept = [bullets[b.id] for b in entry.bullets if b.id in bullets]
    if not kept:
        return 0
    # An experience entry has its own header line plus a separate title line
    # (`render.build_context`'s `job` dict); a project's header line already carries
    # name/tech/date with no second line.
    header_lines = 2 if isinstance(entry, Experience) else 1
    return header_lines + sum(_bullet_lines(text) for text in kept)

def _section_lines(entries: list[Experience] | list[Project], bullets: dict[str, str]) -> int:
    """Lines for one entry section, honoring the bullets filter.

    An entry whose bullets were all dropped contributes nothing at all — not even its
    header — mirroring `render.build_context`'s own filtering.
    """
    per_entry = [_entry_lines(entry, bullets) for entry in entries]
    total = sum(per_entry)
    return total + (1 if total else 0)  # section header, once, if anything survived

def _spacer_lines(resume: MasterResume, bullets: dict[str, str], *, layout: dict) -> int:
    """Blank-separator lines a generic-mode template's spacing donors add on top of
    content lines — see `template_profile.SpacingProfile` and `template_build.
    build_generic`. Zero whenever the active profile has no spacer donors set, so this
    term is a pure addition for a template that actually reproduces blank lines; every
    existing profile (which has none) sizes exactly as before.

    A separate term rather than folded into `_fixed_overhead_lines`/`_section_lines`:
    those two are shared with fixed mode, where no per-section heading spacer exists to
    count, and mixing "which section is first overall" bookkeeping into them is exactly
    where this would get wrong. This only sizes selection; the real render still
    measures, so an error here costs a retry round, not a wrong final page.
    """
    spacing = layout.get("spacing") or {}
    # Each value is a run of chrome paragraph ids (see `template_profile.SpacingProfile`),
    # so its length is how many physical lines that slot costs each time it fires.
    before_n = len(spacing.get("before_heading") or [])
    after_n = len(spacing.get("after_heading") or [])
    between_n = len(spacing.get("between_entries") or [])
    if not (before_n or after_n or between_n):
        return 0

    enabled = layout.get("enabled") or {}
    kind_enabled = {
        "experience": enabled.get("experience", True),
        "project": enabled.get("projects", True),
        "list": enabled.get("list_section", True),
        "education": enabled.get("education", True),
        "skills": enabled.get("skills", True),
    }

    rendered = 0
    between_total = 0
    for section in resume.sections:
        if not kind_enabled.get(section.kind, True):
            continue
        if section.kind in ("experience", "project"):
            surviving = sum(
                1 for e in section.entries if any(b.id in bullets for b in e.bullets)
            )
            if surviving == 0:
                continue
            rendered += 1
            between_total += max(0, surviving - 1)
        elif section.kind == "education":
            if not section.entries:
                continue
            rendered += 1
            between_total += max(0, len(section.entries) - 1)
        else:  # skills / list — never trimmed by selection, render whenever non-empty
            if not section.entries:
                continue
            rendered += 1

    return (
        before_n * max(0, rendered - 1) + after_n * rendered + between_n * between_total
    )

def estimate_lines(
    resume: MasterResume,
    bullets: dict[str, str],
    *,
    layout: dict | None = None,
) -> int:
    """Cheap character-budget estimate of total rendered lines for this bullet set.

    `layout["section_mode"]` changes how many section-header lines same-kind sections
    cost: under `"fixed"` (the default — see `template_profile.TemplateProfile.
    section_mode`), every experience-kind section flattens under the one physical
    "EXPERIENCE" heading the template was built with, and likewise for projects — so two
    experience-kind resume sections cost one header line, not two. Under `"generic"`,
    each resume section gets its own tagged heading, so each contributes its own header
    line. Getting this wrong biases the estimate in the direction that costs an extra
    grow-or-shorten round, not a wrong final page — the real render still measures.
    """
    layout = layout if layout is not None else active_layout()
    enabled = layout.get("enabled") or {}
    section_mode = layout.get("section_mode", "fixed")
    total = _fixed_overhead_lines(resume, layout=layout)

    if section_mode == "generic":
        for section in resume.entry_sections:
            if section.kind == "project" and not enabled.get("projects", True):
                continue
            if section.kind == "experience" and not enabled.get("experience", True):
                continue
            total += _section_lines(section.entries, bullets)
        total += _spacer_lines(resume, bullets, layout=layout)
    else:
        if enabled.get("experience", True):
            experience_entries = [
                e for s in resume.entry_sections if s.kind == "experience" for e in s.entries
            ]
            total += _section_lines(experience_entries, bullets)
        if enabled.get("projects", True):
            project_entries = [
                e for s in resume.entry_sections if s.kind == "project" for e in s.entries
            ]
            total += _section_lines(project_entries, bullets)
    return total

def _bullet_cost(bullet: Bullet) -> int:
    # The rewrite is asked for `_TARGET_LINES_PER_BULLET` lines; a shorter source
    # stays shorter.
    return min(_bullet_lines(bullet.text), fit_types._TARGET_LINES_PER_BULLET)

def _is_widow(fits: dict[str, render.LineFit], measured: set[str], bid: str) -> bool:
    return fits[bid].lines > 1 and fits[bid].last_fill < (
        config.WIDOW_MIN_FILL if bid in measured else config.WIDOW_EST_FILL
    )
