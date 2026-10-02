"""Template-analysis data model (paragraph info, field/section candidates, issues, the
result) plus the shared constants and low-level paragraph/document predicates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict, Field

from . import docx_text
from .template_profile import (
    CharSpan,
    TemplateProfile,
)

#: Canonical section keys the pipeline understands.
SECTION_KEYS = ("education", "experience", "projects", "skills")

#: `SectionCandidate.key`/`by_kind` use the legacy plural `"projects"` (matching
#: `SECTION_KEYS` and `EnabledSections.projects`); `template_profile.GenericSectionKind`
#: uses singular `"project"` (matching `data.Section`'s discriminator). Every other key is
#: spelled the same in both places. Without this remap, `DetectedSection(kind="projects")`
#: raises a `ValidationError` the first time a resume has two projects-shaped headings.
_TO_GENERIC_KIND: dict[str, str] = {"projects": "project"}

#: Heading aliases → canonical key. Exact match on stripped uppercase text first;
#: then substring heuristics below.
_HEADING_ALIASES: dict[str, str] = {
    "EDUCATION": "education",
    "ACADEMIC BACKGROUND": "education",
    "ACADEMICS": "education",
    "WORK EXPERIENCES": "experience",
    "WORK EXPERIENCE": "experience",
    "EXPERIENCE": "experience",
    "PROFESSIONAL EXPERIENCE": "experience",
    "EMPLOYMENT": "experience",
    "EMPLOYMENT HISTORY": "experience",
    "PROJECTS": "projects",
    "SELECTED PROJECTS": "projects",
    "PERSONAL PROJECTS": "projects",
    "SELECTED WORK": "projects",
    "SKILLS": "skills",
    "TECHNICAL SKILLS": "skills",
    "TECHNOLOGIES": "skills",
    "ADDITIONAL INFORMATION": "skills",
    "ADDITIONAL INFO": "skills",
}

_DATE_RE = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|november|december)"
    r"[a-z.]*\s+\d{4}"
    r"|(?:\d{4}\s*[-–—]\s*(?:\d{4}|present|current|now))"
    r"|(?:present|current)\b"
)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

_SEP_CANDIDATES = (" \u2022 ", " • ", " | ", " · ", " – ", " — ", " / ", " |")

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ParagraphInfo(_Strict):
    """One body paragraph flattened for the mapping UI."""

    id: int
    text: str
    is_bullet: bool = False
    is_heading_candidate: bool = False
    has_tab: bool = False
    has_hyperlink: bool = False
    run_count: int = 0
    preview: str = ""

class FieldCandidate(_Strict):
    """A suggested character span for one semantic field."""

    field: str
    span: CharSpan
    confidence: float = Field(ge=0.0, le=1.0)
    preview: str = ""
    #: Which detected section (by `SectionCandidate.heading_paragraph_id`) this
    #: candidate belongs to. `None` only for a candidate emitted outside the
    #: per-section loop (there are none left after `_section_field_candidates`
    #: replaced the old kind-wide emission — kept optional so a `FieldCandidate`
    #: constructed elsewhere, e.g. in a test, still validates).
    section_heading_paragraph_id: int | None = None

class SectionCandidate(_Strict):
    """A detected section heading and its body range."""

    key: str
    heading_paragraph_id: int
    heading_text: str
    body_start: int
    body_end: int
    entry_count: int = 0
    bullet_count: int = 0
    confidence: float = Field(ge=0.0, le=1.0)
    aliases_matched: str = ""

class Issue(_Strict):
    """Blocking or non-blocking finding from analysis."""

    code: str
    message: str
    blocking: bool = False

class AnalyzeResult(_Strict):
    """Full preflight report returned by POST /api/template/analyze."""

    source_sha256: str
    paragraphs: list[ParagraphInfo]
    sections: list[SectionCandidate]
    suggested_profile: TemplateProfile | None = None
    field_candidates: list[FieldCandidate] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    ready: bool = False

    @property
    def blockers(self) -> list[Issue]:
        """Issues that prevent installation."""
        return [i for i in self.issues if i.blocking]

@dataclass
class _Para:
    """Internal paragraph view used while scanning."""

    id: int
    paragraph: Paragraph
    text: str
    is_bullet: bool
    has_tab: bool
    has_hyperlink: bool
    runs: list = field(default_factory=list)
    #: `None` for a body-level paragraph; set when this paragraph lives inside a table
    #: cell. See `docx_text.iter_document_paragraphs` — this is the additive sidecar
    #: that lets table-layout detection reason about "does this row have a second
    #: populated cell" without changing what a paragraph id *means*.
    location: docx_text.ParaLocation | None = None

def sha256_bytes(raw: bytes) -> str:
    """Return the hex SHA-256 of `raw`."""
    return hashlib.sha256(raw).hexdigest()

def is_bullet(paragraph: Paragraph) -> bool:
    """True when the paragraph carries Word list numbering properties."""
    return paragraph._p.find(f".//{qn('w:numPr')}") is not None

def has_tab(paragraph: Paragraph) -> bool:
    """True when any run contains a tab element or a literal tab character."""
    for run in paragraph.runs:
        if "\t" in (run.text or ""):
            return True
        if run._r.find(qn("w:tab")) is not None:
            return True
    return False

def has_hyperlink(paragraph: Paragraph) -> bool:
    """True when the paragraph contains a w:hyperlink wrapper."""
    return paragraph._p.find(qn("w:hyperlink")) is not None

def _has_tab_like(p: _Para) -> bool:
    """`p` is laid out as a two-part line: a real tab stop, or — in a table layout — a
    paragraph whose row carries a second populated cell.

    A section heading is never either; an entry header almost always is. This is the
    exact structural role a literal tab plays in a paragraph-layout resume
    ("Company | Location\\tDates"), generalised to a table layout where the same split
    is expressed as two cells instead of text before/after a tab character.
    """
    if p.has_tab:
        return True
    loc = p.location
    return loc is not None and loc.row_content_cells >= 2

def _document_has_tables(doc) -> bool:
    """True when the body contains at least one table."""
    return bool(doc.tables)

def _document_has_textboxes(doc) -> bool:
    """True when a text box holds text (the common multi-column / sidebar cue).

    `w:txbxContent` covers both DrawingML and legacy VML text boxes. Checks paragraphs
    inside table cells too: a text box parked in a cell is just as strong a cue. An
    empty text box (a styled rectangle) is decoration, see `_document_has_drawings`.
    """
    for paragraph, _location in docx_text.iter_document_paragraphs(doc):
        for box in paragraph._p.iter(qn("w:txbxContent")):
            if "".join(t.text or "" for t in box.iter(qn("w:t"))).strip():
                return True
    return False

def _document_has_drawings(doc) -> bool:
    """True when the body has a drawing or VML shape: a rule, an icon, a photo, a logo.

    Not blocking. The build copies paragraphs it does not tag untouched, drawings
    included, and never sends them anywhere near the model.
    """
    for paragraph, _location in docx_text.iter_document_paragraphs(doc):
        p = paragraph._p
        if p.find(f".//{qn('w:drawing')}") is not None or p.find(f".//{qn('w:pict')}") is not None:
            return True
    return False
