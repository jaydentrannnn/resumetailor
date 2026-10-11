"""Quick adjustments on the layout file: margins, font, size, field emphasis."""

from __future__ import annotations

import io

import docx
import pytest
from docx.oxml.ns import qn

from resume_tailor import config
from resume_tailor.document import (
    docx_text,
    skeleton_parse,
    template_adjust,
    template_analyze,
    template_build,
    template_skeleton,
)
from resume_tailor.document.template_adjust import Adjustments, FieldStyle, Margins
from tests.fixtures import _docx_bytes, _full_featured_resume, _table_resume, synthetic_resume


@pytest.fixture
def skeleton(tmp_path, monkeypatch):
    def make(builder):
        raw = _docx_bytes(builder)
        profile = template_analyze.analyze_docx(raw=raw).suggested_profile
        src, tpl = tmp_path / "baseline.docx", tmp_path / "tagged.docx"
        src.write_bytes(raw)
        monkeypatch.setattr(config, "BASELINE_TEMPLATE_PATH", src)
        template_build.build_from_profile(src, tpl, profile)
        return template_skeleton.make_skeleton(tpl, profile, synthetic_resume())

    return make


def _doc(raw: bytes):
    return docx.Document(io.BytesIO(raw))


def test_current_reads_margins_body_size_and_field_emphasis(skeleton):
    current = template_adjust.current(skeleton(_full_featured_resume).raw)
    assert current.margins.left == 1.25
    labels = {f.label: f for f in current.fields}
    assert labels["School"].bold and not labels["Degree"].bold
    assert current.font_size > 0 and current.font_family


def test_size_moves_every_run_by_the_same_amount(skeleton):
    sk = skeleton(_full_featured_resume)
    doc = _doc(sk.raw)
    before = [template_adjust._size(r, doc) for r in template_adjust._runs(doc)]
    body = template_adjust.current(sk.raw).font_size
    out = _doc(template_adjust.apply(sk.raw, Adjustments(font_size=body + 1.5)))
    after = [r.font.size.pt for r in template_adjust._runs(out)]
    assert after == [b + 1.5 for b in before]


def test_font_family_reaches_runs_and_paragraph_marks_and_keeps_xml_order(skeleton):
    raw = template_adjust.apply(skeleton(_table_resume).raw, Adjustments(font_family="Georgia"))
    doc = _doc(raw)
    for paragraph, _loc in docx_text.iter_document_paragraphs(doc):
        ppr = paragraph._p.pPr
        rpr = ppr.find(qn("w:rPr"))
        assert rpr.find(qn("w:rFonts")).get(qn("w:ascii")) == "Georgia"
        tags = [child.tag for child in ppr]
        if qn("w:sectPr") in tags:
            assert tags.index(qn("w:rPr")) < tags.index(qn("w:sectPr"))
        for run in paragraph.runs:
            assert run.font.name == "Georgia"


def test_adjusted_layout_reads_back_ready(skeleton):
    sk = skeleton(_full_featured_resume)
    adj = Adjustments(
        margins=Margins(top=0.5, bottom=0.5, left=0.6, right=0.6),
        fields=[FieldStyle(label="Job title", italic=True)],
    )
    parsed = skeleton_parse.parse_skeleton(template_adjust.apply(sk.raw, adj), sk.meta())
    assert parsed.result.ready, parsed.result.issues
    title_id = parsed.result.suggested_profile.experience.title_paragraph_id
    doc = _doc(parsed.raw)
    paragraphs = [p for p, _loc in docx_text.iter_document_paragraphs(doc)]
    assert paragraphs[title_id].runs[0].italic
    assert round(doc.sections[0].top_margin.inches, 2) == 0.5


def test_separator_rows_report_and_rewrite_the_literal_gaps(skeleton):
    from resume_tailor.document.template_adjust import SeparatorChoices

    sk = skeleton(_full_featured_resume)
    current = template_adjust.current(sk.raw)
    assert current.separators["contact"] == " \u2022 "
    assert current.separators["project_tech"] == " | "
    assert set(current.separators) >= {"tech_items", "project_link", "skills_items", "dates"}
    adj = Adjustments(separators=SeparatorChoices(contact=" | ", project_tech=" \u2013 "))
    raw = template_adjust.apply(sk.raw, adj)
    after = template_adjust.current(raw).separators
    assert after["contact"] == " | " and after["project_tech"] == " \u2013 "
    text = "\n".join(p.text for p, _l in docx_text.iter_document_paragraphs(_doc(raw)))
    assert "«Location» | «Email» | «Phone»" in text
    parsed = skeleton_parse.parse_skeleton(raw, sk.meta())
    assert parsed.result.ready, parsed.result.issues
    assert parsed.result.suggested_profile.contact.separator == " | "


def test_styled_keeps_file_rows_out_of_the_style():
    from resume_tailor.document import template_style
    from resume_tailor.document.template_adjust import SeparatorChoices

    adj = Adjustments(separators=SeparatorChoices(contact=" | ", coursework="; "))
    style = template_adjust.styled(template_style.DEFAULT, adj)
    assert style.separators.coursework == "; "
    assert style.separators.model_dump().keys().isdisjoint({"contact", "project_tech"})


def test_font_change_replaces_only_the_body_font(skeleton):
    """A template with a second font (here the name line) keeps it; the body font moves."""
    doc = _doc(skeleton(_full_featured_resume).raw)
    name = next(p for p, _loc in docx_text.iter_document_paragraphs(doc) if p.text.strip())
    for run in name.runs:
        template_adjust._set_family(run._r.get_or_add_rPr(), "Courier New")
    buffer = io.BytesIO()
    doc.save(buffer)
    raw = buffer.getvalue()

    current = template_adjust.current(raw)
    assert current.font_family != "Courier New"
    assert current.other_fonts == ["Courier New"]

    out = _doc(template_adjust.apply(raw, Adjustments(font_family="Georgia")))
    paragraphs = [p for p, _loc in docx_text.iter_document_paragraphs(out)]
    first = next(p for p in paragraphs if p.text.strip())
    assert {r.font.name for r in first.runs if r.text.strip()} == {"Courier New"}
    rest = [r for p in paragraphs if p is not first for r in p.runs if r.text.strip()]
    assert rest and all(template_adjust._family(r, out) == "Georgia" for r in rest)
    assert template_adjust.current(template_adjust.apply(raw, Adjustments(font_size=12))).other_fonts == [
        "Courier New"
    ]
