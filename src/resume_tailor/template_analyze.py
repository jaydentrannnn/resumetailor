"""Deterministic structural analysis of a single-column resume DOCX.

Produces ranked mapping suggestions and blocking compatibility issues. Never mutates
the document and never calls an LLM — the confirmed mapping is what `template_build`
consumes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict, Field

from . import docx_text
from .template_profile import (
    CharSpan,
    ContactField,
    ContactMapping,
    EducationMapping,
    EnabledSections,
    ExperienceMapping,
    HeaderFieldMapping,
    NormalizationFlags,
    OptionalSpan,
    ProjectsMapping,
    SkillsMapping,
    TemplateProfile,
)

#: Canonical section keys the pipeline understands.
SECTION_KEYS = ("education", "experience", "projects", "skills")

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


def _document_has_tables(doc) -> bool:
    """True when the body contains at least one table."""
    return bool(doc.tables)


def _document_has_textboxes(doc) -> bool:
    """True when any paragraph hosts a drawing/textbox (common multi-column cue)."""
    for paragraph in doc.paragraphs:
        p = paragraph._p
        if p.find(f".//{qn('w:txbxContent')}") is not None:
            return True
        if p.find(f".//{qn('w:drawing')}") is not None:
            return True
    return False


def _classify_heading(text: str) -> tuple[str | None, float, str]:
    """Map heading text to a canonical section key with a confidence score."""
    stripped = text.strip()
    upper = stripped.upper()
    if upper in _HEADING_ALIASES:
        return _HEADING_ALIASES[upper], 1.0, upper

    # Short all-caps lines that contain a known keyword.
    if len(stripped) <= 40 and stripped == stripped.upper() and any(c.isalpha() for c in stripped):
        for alias, key in _HEADING_ALIASES.items():
            if alias in upper or any(tok in upper for tok in alias.split() if len(tok) > 3):
                # Prefer stronger tokens.
                if key == "experience" and "EXPERIENCE" in upper:
                    return key, 0.85, alias
                if key == "education" and "EDUCATION" in upper:
                    return key, 0.85, alias
                if key == "projects" and "PROJECT" in upper:
                    return key, 0.85, alias
                if key == "skills" and ("SKILL" in upper or "TECHNOLOG" in upper):
                    return key, 0.85, alias

    lower = stripped.lower()
    heuristics = (
        ("experience", ("experience", "employment", "work history"), 0.6),
        ("education", ("education", "academic"), 0.6),
        ("projects", ("project",), 0.55),
        ("skills", ("skills", "technologies", "tech stack"), 0.55),
    )
    for key, needles, conf in heuristics:
        if any(n in lower for n in needles) and len(stripped) <= 48:
            return key, conf, needles[0]
    return None, 0.0, ""


def _split_entries(paras: list[_Para]) -> list[list[_Para]]:
    """Group a section body into entries (non-bullet start + following bullets/title)."""
    entries: list[list[_Para]] = []
    for p in paras:
        starts = (not p.is_bullet) and bool(p.text.strip())
        if starts and (not entries or any(x.is_bullet for x in entries[-1])):
            entries.append([p])
        elif entries:
            entries[-1].append(p)
    return entries


def _contact_separator(text: str) -> str:
    """Pick the most likely contact-line separator from the prototype text."""
    for sep in _SEP_CANDIDATES:
        if sep in text:
            return sep
    # Fallback: single bullet character with spaces.
    if "\u2022" in text:
        return " \u2022 "
    if "|" in text:
        return " | "
    return " \u2022 "


def _contact_field_order(text: str) -> list[ContactField]:
    """Infer which contact fields appear and in what order from prototype text."""
    order: list[ContactField] = []
    lower = text.lower()
    # Scan left-to-right by finding earliest match positions.
    finds: list[tuple[int, ContactField]] = []
    if _EMAIL_RE.search(text):
        finds.append((_EMAIL_RE.search(text).start(), "email"))  # type: ignore[union-attr]
    phone = _PHONE_RE.search(text)
    if phone:
        finds.append((phone.start(), "phone"))
    for label, field in (("linkedin", "linkedin"), ("github", "github")):
        idx = lower.find(label)
        if idx >= 0:
            finds.append((idx, field))  # type: ignore[arg-type]
    # Location: leftover leading chunk before first known token, if any.
    if finds:
        first = min(p for p, _ in finds)
        head = text[:first].strip(" \u2022|·/–—\t")
        if head and "@" not in head and not _PHONE_RE.fullmatch(head.replace(" ", "")):
            finds.append((0, "location"))
    elif text.strip():
        finds.append((0, "location"))

    for _, field in sorted(finds, key=lambda t: t[0]):
        if field not in order:
            order.append(field)
    # Always allow the full set at render time; order is preference for present fields.
    for extra in ("location", "email", "phone", "linkedin", "github"):
        if extra not in order:
            order.append(extra)  # type: ignore[arg-type]
    return order


def _span(paragraph_id: int, start: int, end: int) -> CharSpan:
    """Build a CharSpan."""
    return CharSpan(paragraph_id=paragraph_id, start=start, end=end)


def _header_fields_from_text(
    para: _Para,
    *,
    primary: str,
    secondary: str | None,
    date_field: str,
    exclude_after: int | None = None,
) -> tuple[HeaderFieldMapping, list[FieldCandidate]]:
    """Heuristic split of a header line into primary | secondary \\t dates.

    `exclude_after` clips the primary/secondary search region to `text[:exclude_after]`,
    used to keep a trailing hyperlink label (mapped separately as `link`) out of the
    `secondary`/`tech` span — without it, a header with a link but no tech
    (``"Name | Github\\tdate"``) reads the link's own label as `secondary`, giving `tech`
    and `link` the same span and making the build reject them as overlapping.
    """
    text = para.text
    candidates: list[FieldCandidate] = []
    fields: dict[str, OptionalSpan] = {}

    tab_idx = text.find("\t")
    before = text if tab_idx < 0 else text[:tab_idx]
    after = "" if tab_idx < 0 else text[tab_idx + 1 :]

    date_alignment = "tab" if tab_idx >= 0 else "inline"
    if after.strip() or (tab_idx < 0 and _DATE_RE.search(text)):
        if after.strip():
            start = tab_idx + 1
            # Skip leading whitespace after tab.
            while start < len(text) and text[start].isspace():
                start += 1
            end = len(text.rstrip())
            fields[date_field] = OptionalSpan(
                present=True, span=_span(para.id, start, end)
            )
            candidates.append(
                FieldCandidate(
                    field=date_field,
                    span=fields[date_field].span,  # type: ignore[arg-type]
                    confidence=0.9 if tab_idx >= 0 else 0.6,
                    preview=text[start:end],
                )
            )
        else:
            m = _DATE_RE.search(text)
            if m:
                fields[date_field] = OptionalSpan(
                    present=True, span=_span(para.id, m.start(), m.end())
                )
                date_alignment = "inline"
                candidates.append(
                    FieldCandidate(
                        field=date_field,
                        span=fields[date_field].span,  # type: ignore[arg-type]
                        confidence=0.7,
                        preview=m.group(0),
                    )
                )
                before = text[: m.start()].rstrip(" |·/–—")
            else:
                fields[date_field] = OptionalSpan(present=False)
    else:
        fields[date_field] = OptionalSpan(present=False)

    if exclude_after is not None and exclude_after < len(before):
        before = before[:exclude_after]

    # Split before-tab on a pipe-like separator. Only the first two segments become
    # primary/secondary — further segments (e.g. " | Github" on project headers) are
    # left for project-specific link detection so they do not inflate `tech` and then
    # overlap when the link span is merged in.
    sep = None
    for candidate in (" | ", "|", " — ", " – ", " - "):
        if candidate in before:
            sep = candidate
            break
    if sep and secondary:
        parts = [p.strip() for p in before.split(sep) if p.strip()]
        left_s = parts[0] if parts else ""
        right_s = parts[1] if len(parts) > 1 else ""
        if not left_s:
            fields[primary] = OptionalSpan(present=False)
            fields[secondary] = OptionalSpan(present=False)
        else:
            # Map back to offsets in `text` (before is a prefix of text).
            left_start = text.find(left_s)
            if left_start < 0:
                fields[primary] = OptionalSpan(present=False)
                fields[secondary] = OptionalSpan(present=False)
            else:
                fields[primary] = OptionalSpan(
                    present=True,
                    span=_span(para.id, left_start, left_start + len(left_s)),
                )
                candidates.append(
                    FieldCandidate(
                        field=primary,
                        span=fields[primary].span,  # type: ignore[arg-type]
                        confidence=0.85,
                        preview=left_s,
                    )
                )
                if right_s:
                    # Search after the primary so a repeated token cannot point left.
                    right_start = text.find(right_s, left_start + len(left_s))
                    if right_start < 0:
                        fields[secondary] = OptionalSpan(present=False)
                    else:
                        fields[secondary] = OptionalSpan(
                            present=True,
                            span=_span(
                                para.id, right_start, right_start + len(right_s)
                            ),
                        )
                        candidates.append(
                            FieldCandidate(
                                field=secondary,
                                span=fields[secondary].span,  # type: ignore[arg-type]
                                confidence=0.8,
                                preview=right_s,
                            )
                        )
                else:
                    fields[secondary] = OptionalSpan(present=False)
    else:
        primary_text = before.strip()
        if primary_text:
            start = text.find(primary_text)
            fields[primary] = OptionalSpan(
                present=True, span=_span(para.id, start, start + len(primary_text))
            )
            candidates.append(
                FieldCandidate(
                    field=primary,
                    span=fields[primary].span,  # type: ignore[arg-type]
                    confidence=0.7,
                    preview=primary_text,
                )
            )
        else:
            fields[primary] = OptionalSpan(present=False)
        if secondary:
            fields[secondary] = OptionalSpan(present=False)

    header = HeaderFieldMapping(
        header_paragraph_id=para.id,
        fields=fields,
        date_alignment=date_alignment,  # type: ignore[arg-type]
    )
    return header, candidates


def _skills_spans(para: _Para) -> tuple[CharSpan, CharSpan, str] | None:
    """Split a skills line into label + body on the first colon."""
    text = para.text
    if ":" not in text:
        return None
    idx = text.find(":")
    label = text[:idx].rstrip()
    # Include trailing spaces after colon in the separator; body starts at first non-space.
    sep_end = idx + 1
    while sep_end < len(text) and text[sep_end] == " ":
        sep_end += 1
    body = text[sep_end:]
    if not label or not body.strip():
        return None
    label_start = text.find(label)
    return (
        _span(para.id, label_start, label_start + len(label)),
        _span(para.id, sep_end, sep_end + len(body.rstrip())),
        text[idx:sep_end],
    )


def _load_paras(doc) -> list[_Para]:
    """Flatten document body paragraphs into indexed `_Para` records."""
    out: list[_Para] = []
    for i, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text or ""
        out.append(
            _Para(
                id=i,
                paragraph=paragraph,
                text=text,
                is_bullet=is_bullet(paragraph),
                has_tab=has_tab(paragraph),
                has_hyperlink=has_hyperlink(paragraph),
                runs=list(paragraph.runs),
            )
        )
    return out


def analyze_docx(path: str | bytes | None = None, *, raw: bytes | None = None) -> AnalyzeResult:
    """Analyze a DOCX from a filesystem path or in-memory bytes.

    Prefer `raw=` for uploads (hash is of the exact bytes). Path mode reads the file
    and hashes those bytes.
    """
    import tempfile
    from pathlib import Path

    if raw is not None:
        digest = sha256_bytes(raw)
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            doc = docx.Document(str(tmp_path))
        finally:
            tmp_path.unlink(missing_ok=True)
    elif path is not None:
        path_obj = Path(path)
        digest = sha256_bytes(path_obj.read_bytes())
        doc = docx.Document(str(path_obj))
    else:
        raise ValueError("analyze_docx requires path or raw bytes")

    return _analyze_document(doc, digest)


def _analyze_document(doc, digest: str) -> AnalyzeResult:
    """Run structural analysis on an open Document."""
    issues: list[Issue] = []
    paras = _load_paras(doc)

    if _document_has_tables(doc):
        issues.append(
            Issue(
                code="tables",
                message="Document contains tables; only single-column paragraph layouts are supported.",
                blocking=True,
            )
        )
    if _document_has_textboxes(doc):
        issues.append(
            Issue(
                code="textboxes",
                message=(
                    "Document contains drawings or text boxes, which usually means a "
                    "multi-column or sidebar layout. Only single-column body text is supported."
                ),
                blocking=True,
            )
        )

    if len(paras) < 2:
        issues.append(
            Issue(
                code="too_short",
                message="Document needs at least a name line and a contact line.",
                blocking=True,
            )
        )

    paragraph_infos = [
        ParagraphInfo(
            id=p.id,
            text=p.text,
            is_bullet=p.is_bullet,
            is_heading_candidate=bool(_classify_heading(p.text)[0]),
            has_tab=p.has_tab,
            has_hyperlink=p.has_hyperlink,
            run_count=len(p.runs),
            preview=(p.text[:120] + ("…" if len(p.text) > 120 else "")),
        )
        for p in paras
    ]

    # Detect section headings (first match wins per key).
    found: dict[str, SectionCandidate] = {}
    for p in paras:
        if p.is_bullet or not p.text.strip():
            continue
        key, conf, alias = _classify_heading(p.text)
        if key is None:
            continue
        if key in found and found[key].confidence >= conf:
            continue
        found[key] = SectionCandidate(
            key=key,
            heading_paragraph_id=p.id,
            heading_text=p.text.strip(),
            body_start=p.id + 1,
            body_end=len(paras),
            confidence=conf,
            aliases_matched=alias,
        )

    # Resolve body_end from next heading in document order.
    ordered = sorted(found.values(), key=lambda s: s.heading_paragraph_id)
    section_candidates: list[SectionCandidate] = []
    for i, sec in enumerate(ordered):
        end = (
            ordered[i + 1].heading_paragraph_id
            if i + 1 < len(ordered)
            else len(paras)
        )
        body = paras[sec.body_start : end]
        entries = _split_entries(body)
        bullets = sum(1 for x in body if x.is_bullet)
        section_candidates.append(
            sec.model_copy(
                update={
                    "body_end": end,
                    "entry_count": len(entries),
                    "bullet_count": bullets,
                }
            )
        )
    section_by_key = {s.key: s for s in section_candidates}

    if "experience" not in section_by_key:
        issues.append(
            Issue(
                code="missing_experience",
                message="Could not find an Experience / Work Experience section heading.",
                blocking=True,
            )
        )

    field_candidates: list[FieldCandidate] = []
    suggested: TemplateProfile | None = None

    # Name + contact heuristics: first two non-empty non-heading paragraphs.
    content_paras = [
        p
        for p in paras
        if p.text.strip() and not p.is_bullet and _classify_heading(p.text)[0] is None
    ]
    name_id = content_paras[0].id if content_paras else 0
    contact_para = content_paras[1] if len(content_paras) > 1 else None

    if contact_para is None:
        issues.append(
            Issue(
                code="missing_contact",
                message="Could not find a contact line after the name.",
                blocking=True,
            )
        )

    # Manual bullet glyph warning (non-blocking unless no native bullets in experience).
    for p in paras:
        stripped = p.text.lstrip()
        if stripped.startswith(("•", "●", "○", "-", "–", "—")) and not p.is_bullet:
            issues.append(
                Issue(
                    code="manual_bullets",
                    message=(
                        f"Paragraph {p.id} looks like a bullet but is not a Word list item. "
                        "Convert lists to real bullets in Word/Google Docs before uploading."
                    ),
                    blocking=False,
                )
            )
            break

    enabled = EnabledSections(
        education="education" in section_by_key,
        experience="experience" in section_by_key,
        projects="projects" in section_by_key,
        skills="skills" in section_by_key,
    )

    experience_mapping: ExperienceMapping | None = None
    education_mapping: EducationMapping | None = None
    projects_mapping: ProjectsMapping | None = None
    skills_mapping: SkillsMapping | None = None

    if "experience" in section_by_key:
        sec = section_by_key["experience"]
        body = paras[sec.body_start : sec.body_end]
        entries = _split_entries(body)
        if not entries:
            issues.append(
                Issue(
                    code="empty_experience",
                    message="Experience section has no entries to use as a prototype.",
                    blocking=True,
                )
            )
        else:
            # Prefer entry with a tab in the header and a title + bullets.
            def _exp_score(entry: list[_Para]) -> tuple:
                header = entry[0]
                bullets = [x for x in entry[1:] if x.is_bullet]
                titles = [x for x in entry[1:] if not x.is_bullet and x.text.strip()]
                return (
                    1 if header.has_tab else 0,
                    len(header.runs),
                    1 if titles else 0,
                    len(bullets),
                )

            proto = max(entries, key=_exp_score)
            header_para = proto[0]
            header, hcands = _header_fields_from_text(
                header_para, primary="company", secondary="location", date_field="dates"
            )
            field_candidates.extend(hcands)
            titles = [x for x in proto[1:] if not x.is_bullet and x.text.strip()]
            bullets = [x for x in proto[1:] if x.is_bullet]
            if not bullets:
                # Fall back to any bullet in the section.
                bullets = [x for x in body if x.is_bullet]
            if not bullets:
                issues.append(
                    Issue(
                        code="no_experience_bullets",
                        message=(
                            "Experience section has no Word list bullets. "
                            "Entries need real list formatting."
                        ),
                        blocking=True,
                    )
                )
            else:
                title_span: OptionalSpan
                title_pid: int | None
                if titles:
                    t = titles[0]
                    title_span = OptionalSpan(
                        present=True, span=_span(t.id, 0, len(t.text.strip()))
                    )
                    title_pid = t.id
                    field_candidates.append(
                        FieldCandidate(
                            field="title",
                            span=title_span.span,  # type: ignore[arg-type]
                            confidence=0.9,
                            preview=t.text.strip()[:80],
                        )
                    )
                else:
                    title_span = OptionalSpan(present=False)
                    title_pid = None
                    issues.append(
                        Issue(
                            code="inline_title",
                            message=(
                                "No separate job-title paragraph found under the experience "
                                "header. Map a title field or ensure each job has a title line."
                            ),
                            blocking=True,
                        )
                    )
                experience_mapping = ExperienceMapping(
                    heading_paragraph_id=sec.heading_paragraph_id,
                    heading_text=sec.heading_text,
                    prototype_entry_start=header_para.id,
                    header=header,
                    title=title_span,
                    title_paragraph_id=title_pid,
                    bullet_paragraph_id=bullets[0].id,
                )

    if "education" in section_by_key:
        sec = section_by_key["education"]
        body = paras[sec.body_start : sec.body_end]
        entries = _split_entries(body)
        if entries:
            proto = max(
                entries,
                key=lambda e: (1 if e[0].has_tab else 0, len(e[0].runs)),
            )
            header, hcands = _header_fields_from_text(
                proto[0], primary="school", secondary="location", date_field="dates"
            )
            field_candidates.extend(hcands)
            bullets = [x for x in proto[1:] if x.is_bullet] or [
                x for x in body if x.is_bullet
            ]
            if not bullets:
                issues.append(
                    Issue(
                        code="no_education_bullets",
                        message="Education section has no Word list bullets for degree/details.",
                        blocking=True,
                    )
                )
            else:
                degree = bullets[0]
                detail = bullets[1] if len(bullets) > 1 else bullets[0]
                education_mapping = EducationMapping(
                    heading_paragraph_id=sec.heading_paragraph_id,
                    heading_text=sec.heading_text,
                    prototype_entry_start=proto[0].id,
                    header=header,
                    degree_paragraph_id=degree.id,
                    detail_paragraph_id=detail.id,
                )
        else:
            issues.append(
                Issue(
                    code="empty_education",
                    message="Education heading found but the section has no entries.",
                    blocking=False,
                )
            )
            enabled = enabled.model_copy(update={"education": False})

    if "projects" in section_by_key:
        sec = section_by_key["projects"]
        body = paras[sec.body_start : sec.body_end]
        entries = _split_entries(body)
        if entries:
            proto = min(entries, key=lambda e: len(e[0].runs))

            # Detect the link BEFORE splitting name/tech: its own span (not a fixed word
            # list like "Github"/"Demo"/"Live") comes from the hyperlink itself, so any
            # label works. `exclude_after` then keeps that label out of `tech` — without
            # it, a project with a link but no tech ("Name | Github\tdate") reads the
            # label as tech and the two fields end up with the same span, which the
            # builder rejects as an overlap.
            link = OptionalSpan(present=False)
            exclude_after: int | None = None
            if proto[0].has_hyperlink:
                text = proto[0].text
                tab = text.find("\t")
                limit = len(text) if tab < 0 else tab
                in_region = [
                    (s, e)
                    for s, e in docx_text.hyperlink_char_spans(proto[0].paragraph)
                    if e <= limit
                ]
                if in_region:
                    start, end = in_region[-1]
                    link = OptionalSpan(present=True, span=_span(proto[0].id, start, end))
                    exclude_after = start
                    field_candidates.append(
                        FieldCandidate(
                            field="link",
                            span=link.span,  # type: ignore[arg-type]
                            confidence=0.75,
                            preview=text[start:end],
                        )
                    )

            header, hcands = _header_fields_from_text(
                proto[0],
                primary="name",
                secondary="tech",
                date_field="date",
                exclude_after=exclude_after,
            )
            field_candidates.extend(hcands)
            bullets = [x for x in proto[1:] if x.is_bullet] or [
                x for x in body if x.is_bullet
            ]
            if not bullets:
                issues.append(
                    Issue(
                        code="no_project_bullets",
                        message="Projects section has no Word list bullets.",
                        blocking=True,
                    )
                )
            else:
                projects_mapping = ProjectsMapping(
                    heading_paragraph_id=sec.heading_paragraph_id,
                    heading_text=sec.heading_text,
                    prototype_entry_start=proto[0].id,
                    header=header,
                    link=link,
                    bullet_paragraph_id=bullets[0].id,
                )
        else:
            enabled = enabled.model_copy(update={"projects": False})

    if "skills" in section_by_key:
        sec = section_by_key["skills"]
        body = [p for p in paras[sec.body_start : sec.body_end] if p.text.strip()]
        if body:
            proto = next((p for p in body if ":" in p.text), body[0])
            spans = _skills_spans(proto)
            if spans is None:
                issues.append(
                    Issue(
                        code="skills_format",
                        message=(
                            "Skills lines should look like 'Label: item, item'. "
                            "Could not split the prototype line."
                        ),
                        blocking=True,
                    )
                )
            else:
                label_span, body_span, sep = spans
                skills_mapping = SkillsMapping(
                    heading_paragraph_id=sec.heading_paragraph_id,
                    heading_text=sec.heading_text,
                    prototype_paragraph_id=proto.id,
                    label_span=label_span,
                    body_span=body_span,
                    separator=sep,
                )
                field_candidates.append(
                    FieldCandidate(
                        field="skills_label",
                        span=label_span,
                        confidence=0.9,
                        preview=proto.text[label_span.start : label_span.end],
                    )
                )
        else:
            enabled = enabled.model_copy(update={"skills": False})

    for key in ("education", "projects", "skills"):
        if key not in section_by_key:
            issues.append(
                Issue(
                    code=f"omit_{key}",
                    message=f"No {key.title()} section detected; it will be omitted from the template.",
                    blocking=False,
                )
            )

    blockers = [i for i in issues if i.blocking]
    if (
        not blockers
        and experience_mapping is not None
        and contact_para is not None
        and enabled.experience
    ):
        contact = ContactMapping(
            paragraph_id=contact_para.id,
            field_order=_contact_field_order(contact_para.text),
            separator=_contact_separator(contact_para.text),
        )
        suggested = TemplateProfile(
            source_sha256=digest,
            name_paragraph_id=name_id,
            contact=contact,
            enabled=enabled,
            experience=experience_mapping,
            education=education_mapping if enabled.education else None,
            projects=projects_mapping if enabled.projects else None,
            skills=skills_mapping if enabled.skills else None,
            normalization=NormalizationFlags(),
            warnings=[i.message for i in issues if not i.blocking],
        )

    ready = suggested is not None and not blockers
    return AnalyzeResult(
        source_sha256=digest,
        paragraphs=paragraph_infos,
        sections=section_candidates,
        suggested_profile=suggested,
        field_candidates=field_candidates,
        issues=issues,
        ready=ready,
    )


def validate_profile_against_doc(
    profile: TemplateProfile,
    *,
    raw: bytes,
) -> list[Issue]:
    """Re-check a confirmed profile against the exact upload bytes before install."""
    issues: list[Issue] = []
    digest = sha256_bytes(raw)
    if profile.source_sha256 != digest:
        issues.append(
            Issue(
                code="hash_mismatch",
                message=(
                    "Mapping was confirmed against a different file than the one being "
                    "installed. Re-analyze the upload."
                ),
                blocking=True,
            )
        )
        return issues

    result = analyze_docx(raw=raw)
    # Structural re-validation: required paragraphs must still exist and spans fit.
    para_by_id = {p.id: p for p in result.paragraphs}
    if profile.name_paragraph_id not in para_by_id:
        issues.append(
            Issue(
                code="bad_name",
                message=f"Name paragraph {profile.name_paragraph_id} is out of range.",
                blocking=True,
            )
        )
    if profile.contact.paragraph_id not in para_by_id:
        issues.append(
            Issue(
                code="bad_contact",
                message=f"Contact paragraph {profile.contact.paragraph_id} is out of range.",
                blocking=True,
            )
        )

    def _check_span(span: CharSpan | None, label: str) -> None:
        """Blocking issue when `span` is out of range or straddles a tab.

        The tab check matters because `_tag_mapped_header` treats a tab inside a mapped
        span as a hard error at build time (the tab is what keeps a date right-aligned);
        catching it here turns that failure into a readable install-time rejection
        instead of a build crash — or, before that fix existed, a silently garbled
        template.
        """
        if span is None:
            return
        para = para_by_id.get(span.paragraph_id)
        if para is None:
            issues.append(
                Issue(
                    code="bad_span",
                    message=f"{label}: paragraph {span.paragraph_id} missing.",
                    blocking=True,
                )
            )
            return
        if span.end > len(para.text):
            issues.append(
                Issue(
                    code="bad_span",
                    message=(
                        f"{label}: span [{span.start}:{span.end}] exceeds paragraph "
                        f"length {len(para.text)}."
                    ),
                    blocking=True,
                )
            )
            return
        if "\t" in para.text[span.start : span.end]:
            issues.append(
                Issue(
                    code="span_has_tab",
                    message=(
                        f"{label}: span [{span.start}:{span.end}] contains a tab. "
                        "Map date fields after the tab, not through it."
                    ),
                    blocking=True,
                )
            )

    def _present_spans(fields: dict[str, OptionalSpan]) -> list[tuple[str, CharSpan]]:
        """(field name, span) pairs for mapped fields that are actually present."""
        return [
            (name, field.span)
            for name, field in fields.items()
            if field.present and field.span is not None
        ]

    def _check_no_overlap(spans: list[tuple[str, CharSpan]]) -> None:
        """Blocking issue when two mapped fields on the same paragraph overlap.

        Grouped by paragraph because header fields occasionally live off the header
        paragraph (a `date_paragraph_id` on its own line); those never collide.
        """
        by_paragraph: dict[int, list[tuple[str, CharSpan]]] = {}
        for label, span in spans:
            by_paragraph.setdefault(span.paragraph_id, []).append((label, span))
        for paragraph_id, entries in by_paragraph.items():
            ordered = sorted(entries, key=lambda e: e[1].start)
            for (label_a, span_a), (label_b, span_b) in zip(ordered, ordered[1:]):
                if span_b.start < span_a.end:
                    issues.append(
                        Issue(
                            code="overlapping_spans",
                            message=(
                                f"{label_a!r} and {label_b!r} both claim text in "
                                f"paragraph {paragraph_id}: {label_a} ends at "
                                f"{span_a.end}, {label_b} starts at {span_b.start}."
                            ),
                            blocking=True,
                        )
                    )

    def _check_bullet(paragraph_id: int | None, label: str) -> None:
        """Blocking issue when a bullet-prototype paragraph is missing or not a list item."""
        if paragraph_id is None:
            return
        para = para_by_id.get(paragraph_id)
        if para is None:
            issues.append(
                Issue(
                    code="bad_bullet",
                    message=f"{label}: paragraph {paragraph_id} is missing.",
                    blocking=True,
                )
            )
        elif not para.is_bullet:
            issues.append(
                Issue(
                    code="bullet_not_list",
                    message=f"{label}: paragraph {paragraph_id} is not a Word list item.",
                    blocking=True,
                )
            )

    if not profile.enabled.experience:
        issues.append(
            Issue(
                code="experience_required",
                message="Experience section cannot be disabled.",
                blocking=True,
            )
        )
    else:
        exp = profile.experience
        exp_spans = _present_spans(exp.header.fields)
        if exp.title.present and exp.title.span is not None:
            exp_spans.append(("title", exp.title.span))
        for label, span in exp_spans:
            _check_span(span, label)
        _check_no_overlap(exp_spans)
        _check_bullet(exp.bullet_paragraph_id, "experience bullet prototype")

    if profile.enabled.education and profile.education is not None:
        edu = profile.education
        edu_spans = _present_spans(edu.header.fields)
        for label, span in edu_spans:
            _check_span(span, label)
        _check_no_overlap(edu_spans)
        _check_bullet(edu.degree_paragraph_id, "education degree paragraph")
        if edu.detail_paragraph_id is not None:
            _check_bullet(edu.detail_paragraph_id, "education detail paragraph")

    if profile.enabled.projects and profile.projects is not None:
        proj = profile.projects
        proj_spans = _present_spans(proj.header.fields)
        if proj.link.present and proj.link.span is not None:
            proj_spans.append(("link", proj.link.span))
        for label, span in proj_spans:
            _check_span(span, label)
        _check_no_overlap(proj_spans)
        _check_bullet(proj.bullet_paragraph_id, "project bullet prototype")

    if profile.enabled.skills and profile.skills is not None:
        skl = profile.skills
        skl_spans = [("skills_label", skl.label_span), ("skills_body", skl.body_span)]
        for label, span in skl_spans:
            _check_span(span, label)
        _check_no_overlap(skl_spans)
        if skl.prototype_paragraph_id not in para_by_id:
            issues.append(
                Issue(
                    code="bad_span",
                    message=(
                        f"skills prototype: paragraph {skl.prototype_paragraph_id} "
                        "is missing."
                    ),
                    blocking=True,
                )
            )

    return issues
