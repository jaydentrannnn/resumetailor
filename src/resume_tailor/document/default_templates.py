"""Built-in starter templates (plan P3-T).

This module is the only producer of the default templates' baseline documents. Each
one is built here with python-docx from synthetic sample content. It then goes through
the same analyze → profile → `template_build` → verify path as an uploaded file
(`web/template_ops.install_default`). A default template therefore follows the same
contract as a student's own export, and its `main_template.docx` still comes only from
`template_build`.

The baselines are generated rather than committed: `.docx` files are kept out of git
on purpose (see `.gitignore` and the pre-commit path guard). The build is
deterministic, so the same name always yields the same bytes and the same hash.

Fonts are Liberation Serif/Sans, which are metrically compatible with Times New Roman
and Arial. They ship with LibreOffice and in the Docker image, so page-fit measurement
matches what Word shows.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from typing import Literal

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

SectionKind = Literal["education", "experience", "projects", "leadership", "skills", "awards"]

#: Letter page, and the text width the right-aligned date tab stop sits at.
_PAGE_WIDTH_IN = 8.5
_PAGE_HEIGHT_IN = 11.0

#: A fixed timestamp for every zip member, so a rebuild is byte-identical.
_ZIP_DATE = (2024, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class Design:
    """One starter template's look. Every size is in points unless noted."""

    name: str
    label: str
    description: str
    font: str
    body_size: float
    name_size: float
    heading_size: float
    margin_in: float
    center_header: bool
    heading_rule: bool
    title_italic: bool
    #: Space after each heading and between entries (points).
    heading_space_before: float
    entry_space_before: float
    sections: tuple[SectionKind, ...]
    #: Education listed first: the finance/consulting convention. The install offers to
    #: reorder the student's own sections to match.
    education_first: bool = False
    name_caps: bool = False
    contact_separator: str = " • "


DESIGNS: dict[str, Design] = {
    "classic": Design(
        name="classic",
        label="Classic",
        description=(
            "Serif type, centered name, a rule under each heading. A safe default for any field."
        ),
        font="Liberation Serif",
        body_size=10.5,
        name_size=20,
        heading_size=11,
        margin_in=0.7,
        center_header=True,
        heading_rule=True,
        title_italic=True,
        heading_space_before=8,
        entry_space_before=4,
        sections=("education", "experience", "projects", "leadership", "skills", "awards"),
    ),
    "compact": Design(
        name="compact",
        label="Compact",
        description=(
            "Sans-serif type and tight spacing to fit more on one page. Good for technical resumes."
        ),
        font="Liberation Sans",
        body_size=9.5,
        name_size=16,
        heading_size=10,
        margin_in=0.5,
        center_header=False,
        heading_rule=False,
        title_italic=False,
        heading_space_before=6,
        entry_space_before=2,
        sections=("experience", "projects", "education", "leadership", "skills", "awards"),
    ),
    "business": Design(
        name="business",
        label="Business",
        description=(
            "The finance and consulting format: Education first, bold firm, italic role, "
            "dates on the right."
        ),
        font="Liberation Serif",
        body_size=10.5,
        name_size=16,
        heading_size=10.5,
        margin_in=0.6,
        center_header=True,
        heading_rule=True,
        title_italic=True,
        heading_space_before=6,
        entry_space_before=3,
        sections=("education", "experience", "leadership", "projects", "skills", "awards"),
        education_first=True,
        name_caps=True,
        contact_separator=" | ",
    ),
}

# Synthetic sample content. None of it is real; it only gives each section one or two
# entries for the analyzer to learn the formatting from.
_NAME = "Alex Doe"
_CONTACT = ("Irvine, CA", "alex.doe@example.com", "(555) 010-0000", "linkedin.com/in/alexdoe")
_EDUCATION = (
    ("State University", "Irvine, CA", "Sep 2022 – Jun 2026"),
    (
        "Bachelor of Arts in Economics, Minor in Accounting | GPA: 3.7",
        "Relevant Coursework: Corporate Finance, Econometrics, Financial Accounting",
    ),
)
_EXPERIENCE = (
    (
        "Northwind Capital",
        "Los Angeles, CA",
        "Jun 2025 – Aug 2025",
        "Financial Analyst Intern",
        (
            "Built a three-statement model for a consumer retail client and presented the "
            "valuation to the deal team.",
            "Automated a weekly revenue report in Excel and SQL, saving the team four hours "
            "a week.",
        ),
    ),
    (
        "Contoso Market Research",
        "Irvine, CA",
        "Jan 2024 – May 2025",
        "Research Assistant",
        (
            "Cleaned and analyzed survey data for 2,000 respondents using Python and Stata.",
            "Wrote summaries of pricing trends for a monthly client newsletter.",
        ),
    ),
)
_PROJECTS = (
    (
        "Budget Tracker",
        "Python, SQLite",
        "2025",
        (
            "Built a command-line tool that categorizes bank transactions and charts monthly "
            "spending.",
        ),
    ),
    (
        "Housing Price Model",
        "R, Tableau",
        "2024",
        ("Modeled county housing prices with regression and published an interactive dashboard.",),
    ),
)
_LEADERSHIP = (
    (
        "Undergraduate Investment Club",
        "Irvine, CA",
        "Sep 2023 – Present",
        "Treasurer",
        ("Managed a $5,000 student portfolio and led weekly stock pitch meetings for 30 members.",),
    ),
)
_SKILLS = (
    ("Technical", "Excel, SQL, Python, Tableau, PowerPoint"),
    ("Languages", "English, Spanish"),
    ("Interests", "Hiking, chess, personal finance"),
)

_AWARDS = (
    "Bloomberg Market Concepts Certificate (2025)",
    "Dean's Honor List, six quarters",
)

_TITLES: dict[SectionKind, str] = {
    "education": "EDUCATION",
    "experience": "EXPERIENCE",
    "projects": "PROJECTS",
    "leadership": "LEADERSHIP & ACTIVITIES",
    "skills": "SKILLS",
    "awards": "CERTIFICATIONS & AWARDS",
}


class UnknownTemplate(KeyError):
    """No default template has that name."""


def names() -> list[str]:
    return list(DESIGNS)


def design(name: str) -> Design:
    try:
        return DESIGNS[name]
    except KeyError:
        raise UnknownTemplate(name) from None


def build(name: str) -> bytes:
    """The baseline `.docx` for default template ``name``, byte-for-byte reproducible."""
    spec = design(name)
    document = docx.Document()
    _setup_page(document, spec)
    num_id = _bullet_list(document, spec)
    _header(document, spec)
    for kind in spec.sections:
        _heading(document, spec, _TITLES[kind])
        if kind == "education":
            _education(document, spec, num_id)
        elif kind == "experience":
            for company, place, dates, title, bullets in _EXPERIENCE:
                _job(document, spec, num_id, company, place, dates, title, bullets)
        elif kind == "leadership":
            for company, place, dates, title, bullets in _LEADERSHIP:
                _job(document, spec, num_id, company, place, dates, title, bullets)
        elif kind == "projects":
            for title, tech, dates, bullets in _PROJECTS:
                _project(document, spec, num_id, title, tech, dates, bullets)
        elif kind == "skills":
            for label, items in _SKILLS:
                _skill_line(document, spec, label, items)
        elif kind == "awards":
            for text in _AWARDS:
                _bullet(document, spec, num_id, text)
    document.core_properties.author = ""
    document.core_properties.last_modified_by = ""
    document.core_properties.title = f"{spec.label} resume template"
    buffer = io.BytesIO()
    document.save(buffer)
    return _deterministic(buffer.getvalue())


# --- page and styles --------------------------------------------------------------


def _setup_page(document, spec: Design) -> None:
    section = document.sections[0]
    section.page_width = Inches(_PAGE_WIDTH_IN)
    section.page_height = Inches(_PAGE_HEIGHT_IN)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Inches(spec.margin_in))
    normal = document.styles["Normal"]
    normal.font.name = spec.font
    normal.font.size = Pt(spec.body_size)
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attr), spec.font)
    fmt = normal.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing = 1.0


def _text_width_in(spec: Design) -> float:
    return _PAGE_WIDTH_IN - 2 * spec.margin_in


def _paragraph(document, spec: Design, *, space_before: float = 0):
    paragraph = document.add_paragraph()
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(space_before)
    fmt.space_after = Pt(0)
    return paragraph


def _right_tab(paragraph, spec: Design) -> None:
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Inches(_text_width_in(spec)), WD_TAB_ALIGNMENT.RIGHT
    )


def _bullet_list(document, spec: Design) -> str:
    """A one-level bullet list definition in the template's font; returns its numId."""
    root = document.part.numbering_part.element
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), "10")
    multi = OxmlElement("w:multiLevelType")
    multi.set(qn("w:val"), "singleLevel")
    abstract.append(multi)
    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")
    for tag, value in (("w:start", "1"), ("w:numFmt", "bullet"), ("w:lvlText", "•")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), value)
        lvl.append(el)
    jc = OxmlElement("w:lvlJc")
    jc.set(qn("w:val"), "left")
    lvl.append(jc)
    ppr = OxmlElement("w:pPr")
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), "360")
    ind.set(qn("w:hanging"), "216")
    ppr.append(ind)
    lvl.append(ppr)
    rpr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(attr), spec.font)
    rpr.append(fonts)
    lvl.append(rpr)
    abstract.append(lvl)
    first_num = root.find(qn("w:num"))
    if first_num is not None:
        first_num.addprevious(abstract)
    else:
        root.append(abstract)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), "20")
    ref = OxmlElement("w:abstractNumId")
    ref.set(qn("w:val"), "10")
    num.append(ref)
    root.append(num)
    return "20"


# --- content ----------------------------------------------------------------------


def _header(document, spec: Design) -> None:
    align = WD_ALIGN_PARAGRAPH.CENTER if spec.center_header else WD_ALIGN_PARAGRAPH.LEFT
    name = _paragraph(document, spec)
    name.alignment = align
    run = name.add_run(_NAME)
    run.bold = True
    # Caps by formatting, not by text, so the student's own name renders in caps too.
    run.font.all_caps = spec.name_caps
    run.font.size = Pt(spec.name_size)
    contact = _paragraph(document, spec, space_before=2)
    contact.alignment = align
    contact.add_run(spec.contact_separator.join(_CONTACT))


def _heading(document, spec: Design, title: str) -> None:
    paragraph = _paragraph(document, spec, space_before=spec.heading_space_before)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(title)
    run.bold = True
    run.font.size = Pt(spec.heading_size)
    if spec.heading_rule:
        ppr = paragraph._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for attr, value in (
            ("w:val", "single"),
            ("w:sz", "6"),
            ("w:space", "1"),
            ("w:color", "auto"),
        ):
            bottom.set(qn(attr), value)
        borders.append(bottom)
        ppr.append(borders)


def _entry_line(document, spec: Design, left: str, right: str, *, bold_left: bool, space: float):
    paragraph = _paragraph(document, spec, space_before=space)
    paragraph.paragraph_format.keep_with_next = True
    _right_tab(paragraph, spec)
    run = paragraph.add_run(left)
    run.bold = bold_left
    paragraph.add_run("\t" + right)
    return paragraph


def _bullet(document, spec: Design, num_id: str, text: str) -> None:
    paragraph = _paragraph(document, spec)
    ppr = paragraph._p.get_or_add_pPr()
    numpr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), num_id)
    numpr.append(ilvl)
    numpr.append(nid)
    ppr.append(numpr)
    paragraph.add_run(text)


def _education(document, spec: Design, num_id: str) -> None:
    (school, place, dates), details = _EDUCATION
    _entry_line(
        document, spec, f"{school} | {place}", dates, bold_left=True, space=spec.entry_space_before
    )
    for line in details:
        _bullet(document, spec, num_id, line)


def _job(document, spec: Design, num_id: str, company, place, dates, title, bullets) -> None:
    _entry_line(
        document, spec, f"{company} | {place}", dates, bold_left=True, space=spec.entry_space_before
    )
    role = _paragraph(document, spec)
    role.paragraph_format.keep_with_next = True
    run = role.add_run(title)
    run.italic = spec.title_italic
    for text in bullets:
        _bullet(document, spec, num_id, text)


def _project(document, spec: Design, num_id: str, title, tech, dates, bullets) -> None:
    _entry_line(
        document, spec, f"{title} | {tech}", dates, bold_left=True, space=spec.entry_space_before
    )
    for text in bullets:
        _bullet(document, spec, num_id, text)


def _skill_line(document, spec: Design, label: str, items: str) -> None:
    paragraph = _paragraph(document, spec)
    run = paragraph.add_run(f"{label}:")
    run.bold = True
    paragraph.add_run(f" {items}")


def _deterministic(raw: bytes) -> bytes:
    """Rewrite the zip with fixed timestamps and member order so rebuilds match."""
    src = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _strip_core_dates(data)
            member = zipfile.ZipInfo(info.filename, date_time=_ZIP_DATE)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o600 << 16
            dst.writestr(member, data)
    return out.getvalue()


def _strip_core_dates(data: bytes) -> bytes:
    """Pin the created/modified stamps python-docx writes with the current time."""
    return re.sub(
        rb"(<dcterms:(created|modified)[^>]*>)[^<]*(</dcterms:\2>)",
        rb"\g<1>2024-01-01T00:00:00Z\g<3>",
        data,
    )


# --- profile and bundle -----------------------------------------------------------


def analyzed(name: str):
    """``(raw, AnalyzeResult)`` for default template ``name``.

    Raises `RuntimeError` if the analyzer no longer accepts the design. A test covers
    every design, so this only fires after a regression in the analyzer or here.
    """
    from resume_tailor.document import template_analyze

    raw = build(name)
    result = template_analyze.analyze_docx(raw=raw)
    blockers = [i for i in result.issues if i.blocking]
    if result.suggested_profile is None or blockers:
        detail = "; ".join(i.message for i in blockers) or "no profile suggested"
        raise RuntimeError(f"Default template {name!r} no longer analyzes cleanly: {detail}")
    return raw, result


def sample_resume(name: str):
    """The template's own sample content as a `MasterResume` (for previews)."""
    from resume_tailor.importing import resume_import

    raw, result = analyzed(name)
    return resume_import.import_from_analysis(result, docx.Document(io.BytesIO(raw))).resume


def write_bundle(name: str, folder, *, pdf: bool = False) -> list:
    """Write baseline, profile and tagged template (and optionally a filled PDF)."""
    from pathlib import Path

    from resume_tailor.document import render, template_build, template_profile

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    raw, result = analyzed(name)
    baseline = folder / "original_export.docx"
    baseline.write_bytes(raw)
    profile_file = template_profile.save_profile(
        result.suggested_profile, folder / "template_profile.json"
    )
    tagged = folder / "main_template.docx"
    template_build.build_from_profile(baseline, tagged, result.suggested_profile)
    written = [baseline, profile_file, tagged]
    if pdf:
        filled = render.render(
            sample_resume(name),
            template=tagged,
            out=folder / "sample.docx",
            layout=template_profile.active_layout(result.suggested_profile),
        )
        written += [filled, render.to_pdf(filled, folder / "sample.pdf")]
    return written
