"""Tests for profile-driven template tagging (no Word / no network)."""

from __future__ import annotations

import re
from pathlib import Path

import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from resume_tailor import template_analyze, template_build
from tests.test_template_analyze import (
    _add_bullet_numbering,
    _add_hyperlink,
    _docx_bytes,
    _make_bullet,
    _standard_resume,
)


def _run_bold(run) -> bool:
    """Whether a python-docx `Run` is explicitly bold."""
    rpr = run._r.find(qn("w:rPr"))
    if rpr is None:
        return False
    b = rpr.find(qn("w:b"))
    if b is None:
        return False
    val = b.get(qn("w:val"))
    return val is None or val not in ("0", "false")


def _run_has_tab(run) -> bool:
    """Whether a python-docx `Run` carries a real `<w:tab/>` element."""
    return run._r.find(qn("w:tab")) is not None


def _paragraph_containing(doc, needle: str):
    """The single paragraph whose text contains `needle`."""
    matches = [p for p in doc.paragraphs if needle in p.text]
    assert len(matches) == 1, (
        f"expected exactly one paragraph containing {needle!r}, got {len(matches)}: "
        f"{[p.text for p in matches]}"
    )
    return matches[0]


def _run_with_text(paragraph, text: str):
    """The single run in `paragraph` whose text is exactly `text`."""
    matches = [r for r in paragraph.runs if r.text == text]
    assert len(matches) == 1, (
        f"expected exactly one run with text {text!r} in {paragraph.text!r}, "
        f"got {len(matches)}"
    )
    return matches[0]


def _project_resume_with_link(document, *, tech: bool = True) -> None:
    """PROJECTS resume with a bold name run, plain tech run, and a real hyperlink+tab date.

    Mirrors the run structure of an actual Google Docs export: the name and its
    trailing " | " share one bold run, tech is a separate plain run, the link is a real
    `w:hyperlink`, and the date follows a real `<w:tab/>` element.
    """
    num_id = _add_bullet_numbering(document)
    document.add_paragraph("Name")
    document.add_paragraph("email@example.com")
    document.add_paragraph("EDUCATION")
    edu = document.add_paragraph()
    school = edu.add_run("State University | ")
    school.bold = True
    edu.add_run("Remote")
    edu_tab = edu.add_run()
    edu_tab._r.append(OxmlElement("w:tab"))
    edu.add_run("2018 - 2022")
    _make_bullet(document, "BSc Computer Science", num_id)
    document.add_paragraph("WORK EXPERIENCES")
    exp = document.add_paragraph()
    company = exp.add_run("Acme | ")
    company.bold = True
    exp.add_run("Remote")
    exp_tab = exp.add_run()
    exp_tab._r.append(OxmlElement("w:tab"))
    exp.add_run("2020 - Present")
    document.add_paragraph("Engineer")
    _make_bullet(document, "Shipped features.", num_id)
    document.add_paragraph("PROJECTS")
    p = document.add_paragraph()
    name_run = p.add_run("Text-to-SQL Reward Fine-Tuning via RL | ")
    name_run.bold = True
    if tech:
        p.add_run("GRPO, Deeplearn, HuggingFace, SQL | ")
    _add_hyperlink(p, "Github", "https://github.com/example/repo")
    tab_run = p.add_run()
    tab_run._r.append(OxmlElement("w:tab"))
    p.add_run("Jan 2026 - Mar 2026")
    _make_bullet(document, "Built reward functions.", num_id)
    document.add_paragraph("SKILLS")
    sk = document.add_paragraph()
    bold = sk.add_run("Languages:")
    bold.bold = True
    sk.add_run(" Python, SQL")


def test_build_from_profile_inserts_jinja_tags(tmp_path: Path):
    """Profile build produces experience/project loop tags and name/contact placeholders."""
    raw = _docx_bytes(_standard_resume)
    analysis = template_analyze.analyze_docx(raw=raw)
    assert analysis.suggested_profile is not None

    src = tmp_path / "baseline.docx"
    dst = tmp_path / "main_template.docx"
    src.write_bytes(raw)

    template_build.build_from_profile(src, dst, analysis.suggested_profile)
    assert dst.exists()

    doc = docx.Document(str(dst))
    texts = [p.text for p in doc.paragraphs]
    joined = "\n".join(texts)
    assert "{{ name }}" in joined
    assert "{{r contact }}" in joined
    assert any("{%p for job in experience %}" in t for t in texts)
    assert any("{{ job.company }}" in t or "{{ job.title }}" in t for t in texts)
    assert any("{%p for bullet in job.bullets %}" in t for t in texts)
    assert any("{%p for proj in projects %}" in t for t in texts)
    assert any("{%p for group in skills %}" in t for t in texts)


def test_build_omits_disabled_projects(tmp_path: Path):
    """Disabling projects removes that section's loop from the tagged template."""
    raw = _docx_bytes(_standard_resume)
    analysis = template_analyze.analyze_docx(raw=raw)
    profile = analysis.suggested_profile
    assert profile is not None

    profile = profile.model_copy(
        update={
            "enabled": profile.enabled.model_copy(update={"projects": False}),
            "projects": None,
        }
    )

    src = tmp_path / "baseline.docx"
    dst = tmp_path / "main_template.docx"
    src.write_bytes(raw)
    template_build.build_from_profile(src, dst, profile)

    joined = "\n".join(p.text for p in docx.Document(str(dst)).paragraphs)
    assert "{%p for job in experience %}" in joined
    assert "{%p for proj in projects %}" not in joined


def test_legacy_build_requires_exact_headings(tmp_path: Path):
    """Legacy mode still fails loudly when WORK EXPERIENCES is missing."""
    def build(document):
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("EXPERIENCE")
        document.add_paragraph("Acme")

    src = tmp_path / "baseline.docx"
    dst = tmp_path / "out.docx"
    src.write_bytes(_docx_bytes(build))
    code = template_build.build_legacy(src, dst)
    assert code != 0
    assert not dst.exists()


def test_build_project_header_with_github_link(tmp_path: Path):
    """Three-part project headers (name | tech | Github\\tdate) tag without overlap errors."""
    from tests.test_template_analyze import (
        _add_bullet_numbering,
        _add_hyperlink,
        _make_bullet,
    )
    from docx.oxml import OxmlElement

    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        p = document.add_paragraph(
            "Text-to-SQL Reward Fine-Tuning via RL | "
            "GRPO, Deeplearn, HuggingFace, SQL | "
        )
        _add_hyperlink(p, "Github", "https://github.com/example/repo")
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("Jan 2026 - Mar 2026")
        _make_bullet(document, "Built reward functions.", num_id)
        document.add_paragraph("SKILLS")
        sk = document.add_paragraph()
        bold = sk.add_run("Languages:")
        bold.bold = True
        sk.add_run(" Python, SQL")

    raw = _docx_bytes(build)
    analysis = template_analyze.analyze_docx(raw=raw)
    assert analysis.suggested_profile is not None

    src = tmp_path / "baseline.docx"
    dst = tmp_path / "main_template.docx"
    src.write_bytes(raw)
    template_build.build_from_profile(src, dst, analysis.suggested_profile)

    joined = "\n".join(p.text for p in docx.Document(str(dst)).paragraphs)
    assert "{{ proj.name }}" in joined
    assert "{{ proj.tech }}" in joined
    assert "{{ proj.date }}" in joined
    assert "{{r proj.link }}" in joined


def _build_project_template(tmp_path: Path, *, tech: bool = True, keep_link: bool = True):
    """Build the tagged template for `_project_resume_with_link` and return the doc."""
    raw = _docx_bytes(lambda d: _project_resume_with_link(d, tech=tech))
    analysis = template_analyze.analyze_docx(raw=raw)
    assert analysis.suggested_profile is not None
    profile = analysis.suggested_profile
    if not keep_link:
        assert profile.projects is not None
        profile = profile.model_copy(
            update={
                "projects": profile.projects.model_copy(
                    update={"link": template_analyze.OptionalSpan(present=False)}
                )
            }
        )

    src = tmp_path / "baseline.docx"
    dst = tmp_path / "main_template.docx"
    src.write_bytes(raw)
    template_build.build_from_profile(src, dst, profile)
    return docx.Document(str(dst))


def test_project_header_keeps_bold_name_and_plain_tech(tmp_path: Path):
    """The project name tag stays bold; tech, link, and date tags come out plain."""
    doc = _build_project_template(tmp_path)
    header = _paragraph_containing(doc, "{{ proj.name }}")
    assert _run_bold(_run_with_text(header, "{{ proj.name }}"))
    assert not _run_bold(_run_with_text(header, "{{ proj.tech }}"))
    assert not _run_bold(_run_with_text(header, "{{r proj.link }}"))
    assert not _run_bold(_run_with_text(header, "{{ proj.date }}"))


def test_project_header_date_keeps_tab_element(tmp_path: Path):
    """A real <w:tab/> survives immediately before the project date tag."""
    doc = _build_project_template(tmp_path)
    header = _paragraph_containing(doc, "{{ proj.name }}")
    runs = header.runs
    date_idx = next(i for i, r in enumerate(runs) if r.text == "{{ proj.date }}")
    assert any(_run_has_tab(r) for r in runs[:date_idx])
    assert "\t{{ proj.date }}" in header.text or (
        date_idx > 0 and _run_has_tab(runs[date_idx - 1])
    )


def test_no_separator_before_project_link_tag(tmp_path: Path):
    """No doubled/dangling separator sits between the tech tag and the link tag."""
    doc = _build_project_template(tmp_path)
    header = _paragraph_containing(doc, "{{ proj.name }}")
    text = header.text
    assert "{{ proj.tech }}{{r proj.link }}" in text
    assert re.search(r"[|•·–—/]\s*\{\{r proj\.link \}\}", text) is None


def test_project_header_without_tech_maps_link_only(tmp_path: Path):
    """'Name | Github\\tdate' builds without an overlap error and has no dangling separator."""
    doc = _build_project_template(tmp_path, tech=False)
    header = _paragraph_containing(doc, "{{ proj.name }}")
    text = header.text
    assert "{{ proj.tech }}" not in text
    assert "{{ proj.name }}{{r proj.link }}" in text
    assert re.search(r"[|•·–—/]\s*\{\{r proj\.link \}\}", text) is None


def test_unmapped_hyperlink_label_is_dropped(tmp_path: Path):
    """A hyperlink label with no link mapping is dropped, and its separator does not dangle."""
    doc = _build_project_template(tmp_path, keep_link=False)
    header = _paragraph_containing(doc, "{{ proj.name }}")
    text = header.text
    assert "Github" not in text
    assert "{{r proj.link }}" not in text
    assert re.search(r"[|•·–—/]\s*\t", text) is None


def test_skills_prototype_keeps_plain_body_run(tmp_path: Path):
    """The skills label tag stays bold; the entries tag is plain, with the gap preserved."""
    doc = _build_project_template(tmp_path)
    header = _paragraph_containing(doc, "{{ group.label }}")
    assert _run_bold(_run_with_text(header, "{{ group.label }}"))
    assert not _run_bold(_run_with_text(header, "{{ group.entries }}"))
    assert "{{ group.label }}: {{ group.entries }}" in header.text


def test_experience_header_keeps_bold_company_and_plain_location(tmp_path: Path):
    """The experience company tag stays bold; location and dates come out plain."""
    doc = _build_project_template(tmp_path)
    header = _paragraph_containing(doc, "{{ job.company }}")
    assert _run_bold(_run_with_text(header, "{{ job.company }}"))
    assert not _run_bold(_run_with_text(header, "{{ job.location }}"))
    assert not _run_bold(_run_with_text(header, "{{ job.dates }}"))
    assert any(_run_has_tab(r) for r in header.runs)


def test_profile_and_legacy_headers_agree(tmp_path: Path):
    """Profile and legacy builds produce the same bold/plain/tab shape for one header."""
    raw = _docx_bytes(_project_resume_with_link)

    legacy_dst = tmp_path / "legacy.docx"
    src = tmp_path / "baseline.docx"
    src.write_bytes(raw)
    assert template_build.build_legacy(src, legacy_dst) == 0

    analysis = template_analyze.analyze_docx(raw=raw)
    assert analysis.suggested_profile is not None
    profile_dst = tmp_path / "profile.docx"
    template_build.build_from_profile(src, profile_dst, analysis.suggested_profile)

    def tag_bold(doc, tag: str) -> bool:
        header = _paragraph_containing(doc, tag)
        return _run_bold(_run_with_text(header, tag))

    def has_tab(doc) -> bool:
        header = _paragraph_containing(doc, "{{ job.company }}")
        return any(_run_has_tab(r) for r in header.runs)

    legacy_doc = docx.Document(str(legacy_dst))
    profile_doc = docx.Document(str(profile_dst))

    # Legacy bakes "{{ job.company }} | " into one run; profile keeps company and the
    # separator as separate runs. Both are bold either way — compare the *tag's* bold
    # state, not the exact run split, since the split itself is allowed to differ.
    assert tag_bold(legacy_doc, "{{ job.company }} | ") == tag_bold(profile_doc, "{{ job.company }}")
    assert tag_bold(legacy_doc, "{{ job.location }}") == tag_bold(profile_doc, "{{ job.location }}")
    assert tag_bold(legacy_doc, "{{ job.location }}") is False
    assert tag_bold(profile_doc, "{{ job.location }}") is False
    assert has_tab(legacy_doc) == has_tab(profile_doc) is True


def test_span_past_paragraph_end_raises():
    """A field span extending past the paragraph length fails loudly, naming the field."""
    raw = _docx_bytes(_standard_resume)
    from io import BytesIO

    doc = docx.Document(BytesIO(raw))
    para = next(p for p in doc.paragraphs if "Analytical Engines" in p.text)
    with pytest.raises(RuntimeError, match="dates"):
        template_build.replace_span_with_tag(
            para,
            template_analyze.CharSpan(
                paragraph_id=0, start=0, end=len(para.text) + 5
            ),
            "{{ job.dates }}",
            field="dates",
        )


def test_tab_inside_span_raises():
    """A span that straddles a real tab fails loudly instead of dropping the tab."""
    raw = _docx_bytes(_standard_resume)
    from io import BytesIO

    doc = docx.Document(BytesIO(raw))
    para = next(p for p in doc.paragraphs if "Analytical Engines" in p.text)
    tab_idx = para.text.index("\t")
    with pytest.raises(RuntimeError, match="tab"):
        template_build.replace_span_with_tag(
            para,
            template_analyze.CharSpan(
                paragraph_id=0, start=tab_idx - 1, end=tab_idx + 2
            ),
            "{{ job.dates }}",
            field="dates",
        )


def test_overlapping_spans_name_both_fields():
    """Overlapping mapped spans raise, naming both offending fields."""
    raw = _docx_bytes(_standard_resume)
    from io import BytesIO

    doc = docx.Document(BytesIO(raw))
    para = next(p for p in doc.paragraphs if "Analytical Engines" in p.text)
    slices = template_build.docx_text.paragraph_run_slices(para)
    text = template_build.docx_text.paragraph_text(para)
    with pytest.raises(RuntimeError, match=r"(?s)company.*location|location.*company"):
        template_build.build_segments(
            text,
            slices,
            [
                (0, 12, "{{ job.company }}", "company"),
                (8, 20, "{{ job.location }}", "location"),
            ],
        )
