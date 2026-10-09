"""Shared pieces of a .docx import: the result type, ids, tags, field text and hyperlinks."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .. import config
from ..content.data import (
    Bullet,
    MasterResume,
)
from ..document import (
    docx_text,
)
from ..document.analysis_types import _Para
from ..document.template_profile import HeaderFieldMapping

_COURSEWORK_RE = re.compile(r"(?i)^relevant coursework:\s*(.+)$")

_GPA_RE = re.compile(r"(?i)\s*\|\s*GPA:\s*(.+)$")

class ImportedResume(BaseModel):
    """A draft `MasterResume` plus what the importer could not confidently fill in.

    Returned to the caller without writing anything — the web route hands it to the
    editor as unsaved state; the user reviews and saves through the existing
    `PUT /api/master-resume`, the same path a hand edit takes.
    """

    resume: MasterResume
    #: Plain-English notes naming the entry/field a value could not be parsed for, so a
    #: user reviewing the draft knows exactly what to check rather than discovering a
    #: blank field on its own.
    warnings: list[str] = Field(default_factory=list)

#: A typed dash: ``---`` is an em dash and ``--`` an en dash, but only when set off by
#: spaces, so a hyphenated range ("2020--2022" stays) or a word is never touched.
_TYPED_EM = re.compile(r"(?<=\s)-{3}(?=\s)")
_TYPED_EN = re.compile(r"(?<=\s)-{2}(?=\s)")


def normalize_dashes(text: str) -> str:
    """``"Irvine --- Merage"`` -> ``"Irvine — Merage"`` (Word's AutoFormat would have)."""
    return _TYPED_EN.sub("–", _TYPED_EM.sub("—", text))


def _normalize_strings(value: object) -> object:
    if isinstance(value, str):
        return normalize_dashes(value)
    if isinstance(value, list):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_strings(item) for key, item in value.items()}
    return value


def normalize_resume_dashes(resume: MasterResume) -> MasterResume:
    """The draft with typed ``---``/``--`` turned into real dashes in every text field.

    Applied to both import paths after the draft is built, so a Word file and a PDF
    read the same. Ids and urls hold no spaced hyphen runs, so they pass through.
    """
    data = _normalize_strings(resume.model_dump(by_alias=True))
    return MasterResume.model_validate(data)


def with_skill_terms(resume: MasterResume, used_tags: list[str]) -> list[str]:
    """``used_tags`` plus the short terms from the resume's own Skills sections.

    A resume outside the shipped vocabulary packs (nursing, say) would otherwise end up
    with no tag names to suggest from; its Skills lines are the applicant's own list of
    skills, so they join the tag vocabulary. Long phrases are not tags and are skipped.
    """
    terms = {
        config.canonical_tag(item)
        for section in resume.sections
        if section.kind == "skills"
        for group in section.entries
        for item in group.items
        if item.strip() and len(item.split()) <= 3
    }
    return sorted(set(used_tags) | terms)


def _default_vocabulary() -> set[str]:
    """Alias keys and their canonical targets — every tag name the deterministic
    matcher can recognize with no resume-specific vocabulary supplied."""
    return set(config.TAG_ALIASES.keys()) | set(config.TAG_ALIASES.values())

def _fresh_id(label: str, taken: set[str]) -> str:
    """Slugify `label` into an id unique within `taken`, recording it. Mirrors
    `MasterResume._fill_entry_ids`'s own collision suffixing (`-2`, `-3`, …) so an
    imported file's ids look like a hand-authored one's, not a machine's."""
    base = config.slugify(label) or "entry"
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate

def _seed_tags(text: str, vocabulary: set[str]) -> list[str]:
    """Whole-word, case-insensitive substring match against `vocabulary`, canonicalised.

    Deliberately conservative: a false negative (a real skill left untagged) is safe —
    the user or an opt-in LLM pass can add it — while a false positive (tagging a
    bullet with a skill it does not actually claim) would corrupt the fabrication
    guard's own whitelist for that bullet. Whole-word matching keeps a short term like
    "r" or "go" from matching inside an unrelated word.
    """
    lower = text.lower()
    found: set[str] = set()
    for term in vocabulary:
        term = term.strip()
        if not term:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found.add(config.canonical_tag(term))
    return sorted(found)

def _field_text(entry: list[_Para], header: HeaderFieldMapping, field: str) -> str:
    """Slice `header`'s span for `field` out of its own paragraph, or "" when absent.

    Takes the whole entry, not just the header paragraph, because a table layout's
    location/dates fields live on a *different* paragraph than the header (the row's
    other cell) — `header.fields[field].span.paragraph_id` says which one; slicing the
    header paragraph's text unconditionally would silently read the wrong string (or
    the wrong offsets) the moment that's true.
    """
    opt = header.fields.get(field)
    if opt is None or not opt.present or opt.span is None:
        return ""
    para = next((p for p in entry if p.id == opt.span.paragraph_id), None)
    if para is None:
        return ""
    return para.text[opt.span.start : opt.span.end].strip()

def _paragraph_hyperlink_target(
    para: _Para, *, limit: int | None = None
) -> tuple[str, str, int | None]:
    """Return `(label, url, start)` for the last hyperlink in `para` ending at or
    before `limit` (an entry header's tab index, or end of text when None) — mirrors
    `template_analyze`'s own "last hyperlink before the tab" project-link detection.
    `start` is the label's own character offset, for excluding it from the
    primary/secondary field search region (see `_header_fields_from_text`'s
    `exclude_after`).
    """
    if not para.has_hyperlink:
        return "", "", None
    text = para.text
    region_limit = len(text) if limit is None else limit
    in_region = [
        (s, e) for s, e in docx_text.hyperlink_char_spans(para.paragraph) if e <= region_limit
    ]
    if not in_region:
        return "", "", None
    start, end = in_region[-1]
    label = text[start:end]
    url = ""
    for child in para.paragraph._p.xpath("w:hyperlink"):
        target = docx_text.hyperlink_target(para.paragraph, child)
        if target:
            url = target
            break
    return label, url, start

def _import_bullets(bullet_paras: list[_Para], entry_id: str) -> list[Bullet]:
    bullets: list[Bullet] = []
    for i, p in enumerate(bullet_paras, start=1):
        text = p.text.strip()
        if not text:
            continue
        bullets.append(
            Bullet(
                id=f"{entry_id}_b{i}",
                text=text,
                # Coarse draft heuristic, not a claim about the source resume's own
                # writing style: any digit is treated as "carries a metric". The user
                # reviews every imported bullet before saving, same as every other
                # importer field here.
                metric=bool(re.search(r"\d", text)),
            )
        )
    return bullets
