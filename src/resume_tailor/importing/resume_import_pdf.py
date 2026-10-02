"""PDF -> `MasterResume` draft (content only; the layout still comes from a template).

A student's only copy of their resume is often a PDF (Canva, Google Docs, an old
export). This module reads its text layer and produces the same `ImportedResume` draft
the .docx importer does. The user reviews the draft before anything is saved, and a PDF
never becomes a template: tailoring still needs a .docx or a default template.

Pipeline:
1. `extract_lines`: characters from pdfplumber are grouped into rows by baseline, split
   into segments at wide gaps (a tab-aligned date becomes ``"\\t"``), and read column
   by column when the page has a persistent gutter (a two-column design).
2. `clean_lines`: NFKC (ligatures), bullet glyphs become a flag, private-use icon glyphs
   are stripped, repeated headers/footers and page numbers are dropped, and wrapped
   lines are joined back into logical lines.
3. Structuring, in one of two ways:
   - heuristic (always available): headings by text and shared style, entries by
     bullets and dates;
   - model-assisted (opt-in, `use_model=True`): the model is shown the numbered plain
     lines and answers with line numbers plus field strings. Every field string must be
     copied from the lines it cites (`_guard_field`); bullets are line numbers, so their
     text is always the PDF's own. Nothing the model writes reaches the draft unchecked.
4. `_build`: the same `data` models and tag seeding as `resume_import`.

The model call rides the ``extract`` purpose (like `propose.py`), keyed on its
fingerprint plus `_PROMPT_VERSION`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from .. import config
from ..document import analysis_types
from . import pdf_build, pdf_lines, pdf_patterns, pdf_structure
from .import_common import UNTAGGED, ImportedResume, _default_vocabulary

_PROMPT_VERSION = 1


# --------------------------------------------------------------------------------------
# 3b. Model-assisted structure (opt-in)
# --------------------------------------------------------------------------------------


class ImportEntryLLM(BaseModel):
    header_lines: list[int] = Field(default_factory=list)
    primary: str = ""
    secondary: str = ""
    location: str = ""
    dates: str = ""
    bullet_lines: list[int] = Field(default_factory=list)
    detail_lines: list[int] = Field(default_factory=list)


class ImportSectionLLM(BaseModel):
    heading_line: int
    kind: pdf_patterns.SectionKind
    entries: list[ImportEntryLLM] = Field(default_factory=list)


class ImportLLM(BaseModel):
    name_line: int = 0
    sections: list[ImportSectionLLM] = Field(default_factory=list)


_SYSTEM = """\
You organise the text of a resume that was extracted from a PDF. You are given its \
lines, numbered; bullet points start with "• ". Group the lines into sections and \
entries by line number.

Never rewrite, shorten or add text. Every field you return must be copied exactly from \
the lines you cite, and bullets and details are given only as line numbers.

- name_line: the line with the person's name.
- sections: one per section heading line. kind is one of: experience (jobs, \
internships, leadership, research, volunteering, activities with roles), project, \
education, skills, list (certifications, awards, languages, interests, anything that is \
one item per line), summary.
- For experience, project and education sections, one entry per job, project or \
school. header_lines are the lines that name it. primary is the company or \
organisation, the project name, or the school. secondary is the job title, the \
project's technologies, or the degree. location and dates exactly as printed, or empty. \
bullet_lines are its bullet points; detail_lines are its other lines (coursework, GPA, \
honors).
- For skills, list and summary sections, use one entry whose bullet_lines and \
detail_lines list the section's lines in order.
- Leave out only the contact line and page headers or footers."""


def _numbered(lines: list[pdf_lines.Line]) -> str:
    return "\n".join(
        f"[{i}] {'• ' if ln.bullet else ''}{ln.text.replace(chr(9), '   ')}"
        for i, ln in enumerate(lines)
    )


def _cache_path(text: str):
    payload = "\n".join([str(_PROMPT_VERSION), config.fingerprint("extract"), text])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.pdfimport.json"


def _ask_model(lines: list[pdf_lines.Line], *, use_cache: bool = True) -> ImportLLM:
    from ..infra import llm

    text = _numbered(lines)
    path = _cache_path(text)
    if use_cache and path.exists():
        return ImportLLM.model_validate_json(path.read_text(encoding="utf-8"))
    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": f"<lines>\n{text}\n</lines>"}],
        output_format=ImportLLM,
        output_config={"effort": config.effort_for("extract")},
    )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            f"Model did not return a parseable structure (stop_reason={response.stop_reason!r})."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(parsed.model_dump_json(indent=2), encoding="utf-8")
    return parsed


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _guard_field(value: str, source: str) -> str | None:
    """`value` if it is copied from `source` (whitespace/case aside, or a near-exact
    match of one of its segments), else None. This is the import's fabrication guard."""
    value = value.strip()
    if not value:
        return ""
    if _squash(value) in _squash(source):
        return value
    for seg in pdf_structure._split_segments(source):
        if SequenceMatcher(None, _squash(value), _squash(seg)).ratio() >= 0.9:
            return seg
    return None


def _from_model(
    lines: list[pdf_lines.Line], answer: ImportLLM, warnings: list[str]
) -> tuple[int, list[pdf_structure._Draft]]:
    """(index of the first heading, drafts) from the model's answer, every string checked."""
    used: set[int] = set()

    def take(indices: list[int]) -> list[pdf_lines.Line]:
        out = []
        for i in indices:
            if 0 <= i < len(lines) and i not in used:
                used.add(i)
                out.append(lines[i])
        return out

    drafts: list[pdf_structure._Draft] = []
    sections = sorted(
        (s for s in answer.sections if 0 <= s.heading_line < len(lines)),
        key=lambda s: s.heading_line,
    )
    for sec in sections:
        if sec.heading_line in used:
            continue
        used.add(sec.heading_line)
        title = lines[sec.heading_line].text.strip().rstrip(":").strip()
        draft = pdf_structure._Draft(kind=sec.kind, title=title)
        for raw in sec.entries:
            if sec.kind in ("skills", "list", "summary"):
                picked = take(sorted([*raw.bullet_lines, *raw.detail_lines]))
                draft.lines.extend(ln.text for ln in picked)
                continue
            header = take(raw.header_lines)
            source = "\t".join(ln.text for ln in header)
            entry = pdf_structure._Entry()
            for name in ("primary", "secondary", "location", "dates"):
                value = getattr(raw, name)
                checked = _guard_field(value, source)
                if checked is None:
                    warnings.append(
                        f"{title}: dropped {value!r}, which isn't in the PDF's text for that entry."
                    )
                    checked = ""
                setattr(entry, name, checked)
            if not entry.primary and header:
                entry = pdf_structure._parse_header(header, sec.kind)
            entry.bullets = [ln.text.replace("\t", " ") for ln in take(raw.bullet_lines)]
            entry.details = [ln.text for ln in take(raw.detail_lines)]
            if sec.kind == "education":
                entry.details = [*entry.bullets, *entry.details]
                entry.bullets = []
            draft.entries.append(entry)
        drafts.append(draft)
    first = sections[0].heading_line if sections else len(lines)
    unplaced = [
        lines[i].text for i in range(first, len(lines)) if i not in used and lines[i].text.strip()
    ]
    if unplaced:
        shown = "; ".join(repr(t[:60]) for t in unplaced[:5])
        more = f" and {len(unplaced) - 5} more" if len(unplaced) > 5 else ""
        warnings.append(f"{len(unplaced)} line(s) weren't placed in any section: {shown}{more}.")
    return first, drafts


def import_pdf(
    raw: bytes,
    *,
    known_tags: set[str] | None = None,
    use_model: bool = False,
    ask: Callable[[list[pdf_lines.Line]], ImportLLM] | None = None,
) -> ImportedResume:
    """A reviewed-before-saving draft from a PDF's text. Raises `PdfImportError`.

    `use_model` adds the model-assisted structuring pass; any failure there falls back
    to the heuristic draft with a warning, so an unreachable model never blocks import.
    `ask` replaces the model call (tests).
    """
    physical, links = pdf_lines.extract_lines(raw)
    return import_lines(
        pdf_lines.clean_lines(physical), links, known_tags=known_tags, use_model=use_model, ask=ask
    )


def import_lines(
    lines: list[pdf_lines.Line],
    links: list[str],
    *,
    known_tags: set[str] | None = None,
    use_model: bool = False,
    ask: Callable[[list[pdf_lines.Line]], ImportLLM] | None = None,
) -> ImportedResume:
    """Structure already-cleaned logical lines into a draft. Shared by the PDF import
    and the .docx content-only import (`import_layout.import_content_only`)."""
    warnings: list[str] = []
    vocabulary = _default_vocabulary() if known_tags is None else set(known_tags)

    preamble, drafts = pdf_structure._structure(lines)
    if use_model:
        try:
            answer = (ask or _ask_model)(lines)
            model_warnings: list[str] = []
            first, model_drafts = _from_model(lines, answer, model_warnings)
            if model_drafts:
                preamble, drafts = lines[:first], model_drafts
                warnings.extend(model_warnings)
            else:
                warnings.append("The model found no sections; used the built-in reader instead.")
        except Exception as exc:  # the heuristic draft is always a valid answer
            warnings.append(f"Model-assisted import failed ({exc}); used the built-in reader.")

    if not drafts:
        warnings.append(
            "No section headings (Experience, Education…) were recognised; everything "
            "below your name was kept as one list for you to sort in the editor."
        )
        body = preamble[1:]
        preamble = preamble[:1] + [ln for ln in body if _is_contact_line(ln)]
        drafts = [
            pdf_structure._Draft(
                kind="list",
                title="Imported",
                lines=[ln.text for ln in body if not _is_contact_line(ln)],
            )
        ]

    contact, summary = pdf_build._contact(preamble, links, warnings)
    resume = pdf_build._build(contact, summary, drafts, vocabulary, warnings)
    untagged = sum(1 for b in resume.all_bullets() if b.tags == [UNTAGGED])
    if untagged:
        warnings.append(
            f"{untagged} bullet(s) could not be matched to a known tag and were marked "
            f'"{UNTAGGED}"; retag them before saving.'
        )
    return ImportedResume(resume=resume, warnings=warnings, untagged_bullet_count=untagged)


def _is_contact_line(line: pdf_lines.Line) -> bool:
    return bool(
        analysis_types._EMAIL_RE.search(line.text)
        or any(p.search(line.text) for p in pdf_patterns._LINK_RES.values())
    )
