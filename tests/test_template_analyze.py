"""Unit tests for deterministic DOCX template analysis (no Word / no network)."""

from __future__ import annotations

import io

import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from resume_tailor import template_analyze


def _add_bullet_numbering(document) -> str:
    """Install a minimal bullet abstract + num instance; return the numId string."""
    # python-docx creates numbering part lazily; force it via a style-based list then
    # fall back to a hand-rolled abstract if needed.
    numbering = document.part.numbering_part
    root = numbering.element

    abstract_id = "10"
    # Skip if we already added one in this document.
    for anum in root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) == abstract_id:
            break
    else:
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), abstract_id)
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        num_fmt = OxmlElement("w:numFmt")
        num_fmt.set(qn("w:val"), "bullet")
        lvl.append(num_fmt)
        abstract.append(lvl)
        # abstractNum elements must precede w:num
        first_num = root.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            root.append(abstract)

    num_id = "20"
    for num in root.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            return num_id
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), num_id)
    abs_el = OxmlElement("w:abstractNumId")
    abs_el.set(qn("w:val"), abstract_id)
    num.append(abs_el)
    root.append(num)
    return num_id


def _make_bullet(document, text: str, num_id: str):
    """Append a list paragraph with the given numId."""
    paragraph = document.add_paragraph(text)
    pPr = paragraph._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), num_id)
    numPr.append(ilvl)
    numPr.append(nid)
    pPr.append(numPr)
    return paragraph


def _docx_bytes(build) -> bytes:
    """Run `build(document)` and return the saved .docx bytes."""
    document = docx.Document()
    build(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _standard_resume(document) -> None:
    """Minimal single-column resume matching the legacy heading contract."""
    num_id = _add_bullet_numbering(document)
    document.add_paragraph("Ada Lovelace")
    document.add_paragraph("London • ada@example.com • LinkedIn")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("University of London | UK\t2018 - 2022")
    _make_bullet(document, "BSc Computer Science | GPA: 3.9", num_id)
    _make_bullet(document, "Relevant Coursework: Algorithms, Databases", num_id)
    document.add_paragraph("WORK EXPERIENCES")
    document.add_paragraph("Analytical Engines | London\t2022 - Present")
    document.add_paragraph("Software Engineer")
    _make_bullet(document, "Built numerical engines in Python.", num_id)
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Note Engine | Python, FastAPI\t2024")
    _make_bullet(document, "Indexed research notes with embeddings.", num_id)
    document.add_paragraph("SKILLS")
    p = document.add_paragraph()
    run = p.add_run("Languages:")
    run.bold = True
    p.add_run(" Python, SQL")


def test_analyze_standard_resume_is_ready():
    """A well-formed single-column resume yields a suggested profile."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.ready is True
    assert result.suggested_profile is not None
    assert result.suggested_profile.enabled.experience is True
    assert result.suggested_profile.source_sha256 == template_analyze.sha256_bytes(raw)
    keys = {s.key for s in result.sections}
    assert keys == {"education", "experience", "projects", "skills"}


def test_analyze_renamed_experience_heading():
    """'PROFESSIONAL EXPERIENCE' maps to the experience section."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("PROFESSIONAL EXPERIENCE")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert any(s.key == "experience" for s in result.sections)
    assert result.suggested_profile is not None
    assert result.suggested_profile.enabled.education is False
    assert result.suggested_profile.enabled.projects is False


def test_analyze_missing_experience_is_blocking():
    """No experience heading → ready false with a blocker."""
    def build(document):
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("SKILLS")
        document.add_paragraph("Languages: Python")

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.ready is False
    assert any(i.code == "missing_experience" and i.blocking for i in result.issues)


def test_analyze_tables_are_blocking():
    """Tables are rejected as unsupported layouts."""
    def build(document):
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Acme"
        table.cell(0, 1).text = "Engineer"

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert any(i.code == "tables" and i.blocking for i in result.issues)


def test_validate_profile_hash_mismatch():
    """Installing with a profile from a different file is rejected."""
    raw_a = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw_a)
    assert result.suggested_profile is not None
    profile = result.suggested_profile

    raw_b = _docx_bytes(lambda d: (d.add_paragraph("Other"), d.add_paragraph("x@y.z")))
    issues = template_analyze.validate_profile_against_doc(profile, raw=raw_b)
    assert any(i.code == "hash_mismatch" and i.blocking for i in issues)


def test_contact_separator_detection():
    """Pipe-separated contact lines become ' | ' separators."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("City | a@b.co | LinkedIn")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Did work.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    assert "|" in result.suggested_profile.contact.separator


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    """Append a real w:hyperlink run so analyze's has_hyperlink path fires."""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    new_run.append(rPr)
    text_el = OxmlElement("w:t")
    text_el.text = text
    new_run.append(text_el)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def test_project_header_name_tech_github_no_overlap():
    """name | tech | Github\\tdate must not fold Github into the tech span."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        # Mirror the live resume: name | tech | Github\\tdates with a real hyperlink.
        p = document.add_paragraph(
            "Text-to-SQL Reward Fine-Tuning via RL | "
            "GRPO, Deeplearn, HuggingFace, SQL | "
        )
        _add_hyperlink(p, "Github", "https://github.com/example/repo")
        # Tab + dates as a following run (python-docx paragraph.text joins them).
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("Jan 2026 - Mar 2026")
        _make_bullet(document, "Built reward functions.", num_id)

    raw = _docx_bytes(build)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.ready is True
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    tech = projects.header.fields.get("tech")
    assert tech is not None and tech.present and tech.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    tech_preview = header_text[tech.span.start : tech.span.end]
    assert "Github" not in tech_preview
    assert "GRPO" in tech_preview
    assert projects.link.present is True
    assert projects.link.span is not None
    link_preview = header_text[projects.link.span.start : projects.link.span.end]
    assert link_preview == "Github"
    assert tech.span.end <= projects.link.span.start


def test_project_link_label_comes_from_hyperlink_text():
    """The link span is derived from the hyperlink's own text, not a fixed word list."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        p = document.add_paragraph("Note Engine | Python, FastAPI | ")
        _add_hyperlink(p, "Source", "https://example.com/source")
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("2024")
        _make_bullet(document, "Indexed notes.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    assert projects.link.present is True
    assert projects.link.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    assert header_text[projects.link.span.start : projects.link.span.end] == "Source"


def test_project_header_without_tech_does_not_duplicate_link_span():
    """'Name | Github\\tdate' maps only the link, not an overlapping tech span."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        p = document.add_paragraph("Solo Proj | ")
        _add_hyperlink(p, "Github", "https://github.com/example/solo")
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("Jan 2026")
        _make_bullet(document, "Shipped solo.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    tech = projects.header.fields.get("tech")
    assert tech is None or not tech.present
    assert projects.link.present is True
    assert projects.link.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    assert header_text[projects.link.span.start : projects.link.span.end] == "Github"


def test_validate_rejects_tab_inside_span():
    """A mapped span that straddles a real tab is rejected as blocking."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.suggested_profile is not None
    profile = result.suggested_profile
    exp = profile.experience
    dates_span = exp.header.fields["dates"].span
    assert dates_span is not None
    bad_span = dates_span.model_copy(update={"start": dates_span.start - 1})
    bad_fields = dict(exp.header.fields)
    bad_fields["dates"] = bad_fields["dates"].model_copy(update={"span": bad_span})
    bad_profile = profile.model_copy(
        update={
            "experience": exp.model_copy(
                update={"header": exp.header.model_copy(update={"fields": bad_fields})}
            )
        }
    )
    issues = template_analyze.validate_profile_against_doc(bad_profile, raw=raw)
    assert any(i.code == "span_has_tab" and i.blocking for i in issues)


def test_validate_rejects_overlapping_spans():
    """Two mapped fields claiming the same text on one paragraph are rejected."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.suggested_profile is not None
    profile = result.suggested_profile
    exp = profile.experience
    company_span = exp.header.fields["company"].span
    assert company_span is not None
    bad_fields = dict(exp.header.fields)
    bad_fields["location"] = bad_fields["location"].model_copy(
        update={"span": company_span}
    )
    bad_profile = profile.model_copy(
        update={
            "experience": exp.model_copy(
                update={"header": exp.header.model_copy(update={"fields": bad_fields})}
            )
        }
    )
    issues = template_analyze.validate_profile_against_doc(bad_profile, raw=raw)
    assert any(i.code == "overlapping_spans" and i.blocking for i in issues)
