"""Expanded experience descriptions for application-form paste fields.

A fourth LLM stage, separate from the page-fitted resume rewrite. Application forms ask
for a fuller description of each role — title, company, dates, location, and a free-text
description — and those fields are rarely line-budgeted the way a one-page resume is.

Hard facts (title, company, location, start, end) are never asked of the model: they are
copied from `MasterResume` in code and joined onto the generated bullets. The model
returns only bullet strings keyed by `entry_key`.

The fabrication guard still runs, but a failing bullet is dropped with a warning rather
than raising — this artifact is advisory text a human edits before pasting, and must not
fail a run whose `.docx` already succeeded.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, events, llm
from .data import Bullet, Experience, MasterResume
from .fit import FitResult
from .jd import JobRequirements
from .rewrite import (
    _check_fabrication,
    _format_keywords,
    numbers_dropped,
    select_entries,
    verb_collisions,
)


#: Bumped when `_SYSTEM` or the expand request shape changes, so stored expansions
#: invalidate on their own rather than relying on `--no-cache`.
_EXPAND_PROMPT_VERSION = 1

#: How far below the hard char limit the advertised target range opens. Same lesson as
#: `rewrite._TARGET_BAND`: a bare ceiling lets the model land two characters over.
_TARGET_BAND = 150

#: Leading list glyphs some models prepend even when asked for plain bullets.
_LEADING_GLYPH = re.compile(r"^[\s•\-\*\u2022\u00b7]+")


_SYSTEM = """\
You expand a candidate's work-experience entries into fuller descriptions for an online \
application form's "Experience" / "Description" fields.

These fields are NOT a resume page. They usually allow 1,500–2,000 characters and are \
read by recruiters and ATS keyword search. Expand beyond the compressed resume bullets: \
decompose each source bullet into the distinct accomplishments it packs, and write one \
action-verb-led bullet per accomplishment.

Absolute rules:
- NEVER invent a skill, tool, technology, metric, employer, title, date, or claim that is \
not already present in the source bullets (and their permitted_skills) for that entry. \
You are expanding and rewording, not embellishing.
- Preserve every number exactly as written. Do not round, restate, or infer new figures.
- Mirror the posting's wording only where it names something the source already does, and \
only when the two genuinely mean the same thing. A keyword the source cannot honestly \
claim is meant to go unused.
- Soft skills are shown by the work, never named. Do not open a bullet by asserting \
communication, collaboration, problem-solving, organisation, attention to detail, or \
teamwork.
- Write bullets, not paragraphs. One accomplishment per bullet, strong verb first. No \
first person. No leading bullet glyphs (•, -, *) — return plain text only.
- Vary the opening verb within each entry. No two bullets in the same entry may open with \
the same verb, and no more than two may open with near-synonyms.
- Each entry gives a `target` character range and a hard `max` for the *combined* text of \
its bullets (joined with newlines). Err short of `max`, never long — some forms truncate \
silently past the limit.
- Aim for 5–8 bullets per entry when the source material supports it; fewer is fine when \
the entry is thin.

Return one entry per input item, keyed by the exact entry_key you were given. Do not \
return title, company, dates, or location — those are filled in by code.
"""


class ExpandedEntryLLM(BaseModel):
    """One entry's bullets as returned by the model — strings only, no hard facts."""

    entry_key: str
    bullets: list[str] = Field(default_factory=list)


class ExpansionLLMResult(BaseModel):
    """Batched model output for every expanded experience entry."""

    entries: list[ExpandedEntryLLM] = Field(default_factory=list)


@dataclass
class ExpandedEntry:
    """One experience entry ready to paste into an application form."""

    entry_key: str
    title: str
    company: str
    location: str
    start: str
    end: str
    bullets: list[str] = field(default_factory=list)
    char_count: int = 0
    warnings: list[str] = field(default_factory=list)
    #: True when this entry also appears on the tailored resume.
    on_resume: bool = False


@dataclass
class Expansion:
    """Full expansion artifact for one tailoring run."""

    entries: list[ExpandedEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    char_limit: int = 0


def entry_key(index: int) -> str:
    """Stable key for an experience entry at `index` in `MasterResume.experience`."""
    return f"exp:{index}"


def _experience_index(resume: MasterResume, entry: Experience) -> int:
    """Return the index of `entry` in `resume.experience`, or raise if missing."""
    for i, candidate in enumerate(resume.experience):
        if candidate is entry:
            return i
    raise ValueError(f"Experience entry {entry.company!r} is not on the master resume.")


def choose_entries(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    resume_bullet_ids: set[str] | None = None,
    semantic: dict[str, float] | None = None,
    limit: int | None = None,
) -> list[Experience]:
    """Pick experience entries for expansion, forcing in every entry on the tailored resume.

    Ranking reuses `rewrite.score_entry` / `select_entries` so the tile cannot disagree
    with the resume about which job mattered. Entries that contributed at least one
    bullet to `FitResult.bullets` are always included, even when that pushes past `limit`
    — the form should never omit a role the applicant just put on the PDF.
    """
    limit = limit if limit is not None else config.MAX_EXPANDED_ENTRIES
    resume_bullet_ids = resume_bullet_ids or set()

    forced = [
        e
        for e in resume.experience
        if any(b.id in resume_bullet_ids for b in e.bullets)
    ]
    forced_ids = {id(e) for e in forced}

    remaining_budget = max(0, limit - len(forced))
    pool = [e for e in resume.experience if id(e) not in forced_ids]
    extras = (
        select_entries(pool, requirements, limit=remaining_budget, semantic=semantic)
        if remaining_budget
        else []
    )

    chosen_ids = forced_ids | {id(e) for e in extras}
    # Preserve master-resume order (reverse chronological) for paste readability.
    return [e for e in resume.experience if id(e) in chosen_ids]


def _length_band(limit: int) -> tuple[int, int]:
    """Soft minimum and hard maximum character counts advertised for one entry."""
    hard_max = max(200, limit - 50)
    return max(100, hard_max - _TARGET_BAND), hard_max


def _cache_path(
    keyed: list[tuple[str, Experience]],
    requirements: JobRequirements,
    *,
    char_limit: int,
) -> Path:
    """Cache key covering everything the expansion depends on.

    Keys must be the master-resume `exp:<index>` values, not positions in the filtered
    list — otherwise editing an earlier entry would not invalidate a later one's cache.
    """
    payload = "\n".join(
        [
            str(_EXPAND_PROMPT_VERSION),
            config.fingerprint("expand"),
            str(char_limit),
            requirements.model_dump_json(),
            *(
                f"{key}\t{e.company}\t{e.title}\t"
                + "\t".join(f"{b.id}:{b.text}" for b in e.bullets)
                for key, e in keyed
            ),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.expansion.json"


def _format_entries(entries: list[tuple[str, Experience]], char_limit: int) -> str:
    """Build the per-entry XML block for the expand user message."""
    soft_min, hard_max = _length_band(char_limit)
    blocks: list[str] = []
    for key, entry in entries:
        bullet_lines = "\n".join(
            f"    <bullet id={b.id!r}>\n"
            f"      <current>{b.text}</current>\n"
            f"      <permitted_skills>{', '.join(b.tags)}</permitted_skills>\n"
            f"    </bullet>"
            for b in entry.bullets
        )
        blocks.append(
            f"<entry key={key!r} target={f'{soft_min}-{hard_max}'!r} max={hard_max}>\n"
            f"  <role>{entry.title} at {entry.company}</role>\n"
            f"  <source_bullets>\n{bullet_lines}\n  </source_bullets>\n"
            f"</entry>"
        )
    return "\n".join(blocks)


def _clean_bullet(text: str) -> str:
    """Strip leading list glyphs and surrounding whitespace from one model bullet."""
    return _LEADING_GLYPH.sub("", text.strip()).strip()


def _description_text(bullets: list[str]) -> str:
    """Join bullets the way the copy-paste tile and forms expect them."""
    return "\n".join(bullets)


def _accept_bullets(
    entry: Experience,
    raw_bullets: list[str],
    *,
    char_limit: int,
) -> tuple[list[str], list[str]]:
    """Filter model bullets through the fabrication guard and length budget.

    Returns `(kept_bullets, warnings)`. Guard failures drop the bullet; length overflow
    truncates from the end (last bullets first) so earlier, usually stronger claims stay.
    """
    warnings: list[str] = []
    kept: list[str] = []
    dropped_terms: list[str] = []

    for raw in raw_bullets:
        text = _clean_bullet(raw)
        if not text:
            continue
        offenders = _check_fabrication(entry.bullets, text)
        if offenders:
            dropped_terms.extend(offenders)
            continue
        kept.append(text)

    if dropped_terms:
        unique = list(dict.fromkeys(dropped_terms))
        warnings.append(
            f"{len(unique)} unsupported term(s) caused bullet drops: {', '.join(unique)}"
        )

    # Numbers present in any source bullet must still appear somewhere in the expansion.
    missing = numbers_dropped(entry.bullets, _description_text(kept))
    if missing:
        warnings.append(f"Source number(s) missing from expansion: {', '.join(missing)}")

    # Verb collisions within the entry are advisory — do not drop, just warn.
    numbered = {str(i): b for i, b in enumerate(kept)}
    collisions = verb_collisions(numbered)
    if collisions:
        warnings.append(
            f"{len(collisions)} bullet(s) share an opening verb with an earlier one"
        )

    # Trim from the end until under the hard cap.
    while kept and len(_description_text(kept)) > char_limit:
        kept.pop()
        if "Trimmed bullets to fit the character limit" not in warnings:
            warnings.append("Trimmed bullets to fit the character limit")

    return kept, warnings


def format_markdown(expansion: Expansion) -> str:
    """Render the expansion as plain text suitable for a single copy-all action."""
    blocks: list[str] = []
    for entry in expansion.entries:
        header = f"{entry.title} · {entry.company}"
        meta_parts = [p for p in (entry.location, f"{entry.start} – {entry.end}") if p]
        if meta_parts:
            header += f"\n{' · '.join(meta_parts)}"
        body = "\n".join(f"• {b}" for b in entry.bullets)
        blocks.append(f"{header}\n\n{body}" if body else header)
    return "\n\n---\n\n".join(blocks)


def expand_experience(
    resume: MasterResume,
    requirements: JobRequirements,
    *,
    fit_result: FitResult | None = None,
    semantic: dict[str, float] | None = None,
    limit: int | None = None,
    char_limit: int | None = None,
    use_cache: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> Expansion:
    """Generate expanded experience descriptions for application-form paste fields.

    Selection is deterministic. The LLM call is one batched request for all chosen
    entries. Hard facts are joined from `resume` after the call — the model never emits
    them. Fabrication failures drop individual bullets; they never raise.
    """
    char_limit = char_limit if char_limit is not None else config.EXPAND_CHAR_LIMIT
    resume_ids = set(fit_result.bullets) if fit_result is not None else set()
    chosen = choose_entries(
        resume,
        requirements,
        resume_bullet_ids=resume_ids,
        semantic=semantic,
        limit=limit,
    )
    model_label = config.backend_for("expand").label()

    if not chosen:
        events.emit(on_event, "expand", "No experience entries to expand")
        return Expansion(entries=[], warnings=[], model=model_label, char_limit=char_limit)

    keyed = [(entry_key(_experience_index(resume, e)), e) for e in chosen]
    by_key = {key: entry for key, entry in keyed}

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(keyed, requirements, char_limit=char_limit)
    llm_result: ExpansionLLMResult | None = None

    if use_cache and cache_path.exists():
        events.emit(on_event, "expand", "Reusing cached experience expansion", cached=True)
        llm_result = ExpansionLLMResult.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    else:
        events.emit(
            on_event,
            "expand",
            f"Expanding {len(chosen)} experience entr{'y' if len(chosen) == 1 else 'ies'}",
            cached=False,
            entries=len(chosen),
            model=config.model_for("expand"),
        )
        notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
        user = (
            f"<role>{requirements.title} ({requirements.seniority})</role>\n\n"
            f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n"
            f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n"
            f"</keywords_to_mirror>\n\n"
            f"<entries_to_expand>\n{_format_entries(keyed, char_limit)}\n"
            f"</entries_to_expand>"
        )
        client = llm.client_for("expand")
        response = client.messages.parse(
            model=config.model_for("expand"),
            max_tokens=config.max_tokens_for("expand"),
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=ExpansionLLMResult,
            output_config={"effort": config.effort_for("expand")},
        )
        llm_result = response.parsed_output
        if llm_result is None:
            raise RuntimeError(
                f"Model did not return a parseable expansion "
                f"(stop_reason={response.stop_reason!r})."
            )
        # Keep only keys we asked for before caching, so a hallucinated key cannot poison
        # a later reuse.
        llm_result = ExpansionLLMResult(
            entries=[e for e in llm_result.entries if e.entry_key in by_key]
        )
        cache_path.write_text(llm_result.model_dump_json(indent=2), encoding="utf-8")

    returned = {e.entry_key: e.bullets for e in llm_result.entries}
    entries_out: list[ExpandedEntry] = []
    top_warnings: list[str] = []

    for key, entry in keyed:
        kept, warnings = _accept_bullets(
            entry, returned.get(key, []), char_limit=char_limit
        )
        if key not in returned:
            warnings.append("Model omitted this entry; no bullets generated")
        on_resume = any(b.id in resume_ids for b in entry.bullets)
        entries_out.append(
            ExpandedEntry(
                entry_key=key,
                title=entry.title,
                company=entry.company,
                location=entry.location,
                start=entry.start,
                end=entry.end,
                bullets=kept,
                char_count=len(_description_text(kept)),
                warnings=warnings,
                on_resume=on_resume,
            )
        )

    return Expansion(
        entries=entries_out,
        warnings=top_warnings,
        model=model_label,
        char_limit=char_limit,
    )
