"""Bullet style chosen in Quick adjustments, applied on the built template."""

from __future__ import annotations

import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from resume_tailor import config
from resume_tailor.document import (
    docx_text,
    skeleton_parse,
    template_analyze,
    template_build,
    template_bullets,
    template_skeleton,
    template_tags,
)
from resume_tailor.document.template_style import Bullets, TemplateStyle
from tests.fixtures import _docx_bytes, _full_featured_resume, synthetic_resume


def _indented_resume(document) -> None:
    """`_full_featured_resume` with the hanging indent a real export gives its bullets."""
    _full_featured_resume(document)
    for paragraph in document.paragraphs:
        ppr = paragraph._p.pPr
        if ppr is not None and ppr.find(qn("w:numPr")) is not None:
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), "540")
            ind.set(qn("w:hanging"), "360")
            ppr.append(ind)


@pytest.fixture
def build(tmp_path, monkeypatch):
    raw = _docx_bytes(_indented_resume)
    base = template_analyze.analyze_docx(raw=raw).suggested_profile
    src = tmp_path / "baseline.docx"
    src.write_bytes(raw)
    monkeypatch.setattr(config, "BASELINE_TEMPLATE_PATH", src)

    def make(list_choice="keep", skills="keep", source=src, profile=None, name="tagged.docx"):
        style = TemplateStyle(bullets=Bullets(list=list_choice, skills=skills))
        profile = (profile or base).model_copy(update={"style": style})
        out = tmp_path / name
        template_build.build_from_profile(source, out, profile)
        return docx.Document(str(out)), profile, out

    return make


def _tagged(doc, tag):
    return [p for p, _l in docx_text.iter_document_paragraphs(doc) if tag in p.text]


def _lvl0(doc, paragraph):
    root = doc.part.numbering_part.element
    num_id = template_bullets._paragraph_num_id(paragraph)
    abstract = template_bullets._num_to_abstract(root)[num_id]
    anum = next(a for a in root.findall(qn("w:abstractNum"))
                if a.get(qn("w:abstractNumId")) == abstract)  # fmt: skip
    return next(lvl for lvl in anum.findall(qn("w:lvl")) if lvl.get(qn("w:ilvl")) == "0")


def _marker(doc, paragraph) -> str | None:
    text = _lvl0(doc, paragraph).find(qn("w:lvlText"))
    return None if text is None else text.get(qn("w:val"))


def _ind(paragraph) -> dict:
    ind = paragraph._p.pPr.find(qn("w:ind"))
    return {} if ind is None else {k.split("}")[1]: v for k, v in ind.attrib.items()}


def test_keep_changes_nothing(build):
    keep, _p, _o = build(name="keep.docx")
    doc, _p, _o = build("keep", "keep")
    bullet = _tagged(doc, template_tags.BULLET_TAG)[0]
    assert _marker(doc, bullet) == _marker(keep, _tagged(keep, template_tags.BULLET_TAG)[0])
    assert template_bullets._paragraph_num_id(bullet) == template_bullets._paragraph_num_id(
        _tagged(keep, template_tags.BULLET_TAG)[0]
    )


def test_a_glyph_moves_every_list_onto_one_copy_with_that_marker(build):
    keep, _p, _o = build(name="keep.docx")
    original = template_bullets._paragraph_num_id(_tagged(keep, template_tags.BULLET_TAG)[0])
    doc, _p, _o = build("•")
    paragraphs = _tagged(doc, template_tags.BULLET_TAG) + _tagged(
        doc, template_tags.EDUCATION_DETAIL_TAG
    )
    ids = {template_bullets._paragraph_num_id(p) for p in paragraphs}
    assert len(ids) == 1 and original not in ids
    assert _marker(doc, paragraphs[0]) == "•"
    # The source list still draws its own marker for anything else that uses it.
    assert template_bullets._list_glyph(doc, original) is None
    order = [el.tag.split("}")[1] for el in _lvl0(doc, paragraphs[0])]
    assert order.index("numFmt") < order.index("lvlText")
    # A text-sized marker is not shrunk like the large disc.
    mark = paragraphs[0]._p.pPr.find(qn("w:rPr"))
    sz = mark.find(qn("w:sz")) if mark is not None else None
    body = template_bullets._body_run_size(paragraphs[0])
    assert sz is None or int(sz.get(qn("w:val"))) == body


def test_none_indented_keeps_the_text_where_it_was(build):
    keep, _p, _o = build(name="keep.docx")
    before = _ind(_tagged(keep, template_tags.BULLET_TAG)[0])
    doc, _p, _o = build("none_indent")
    bullet = _tagged(doc, template_tags.BULLET_TAG)[0]
    assert before == {"left": "540", "hanging": "360"}
    assert _marker(doc, bullet) == ""
    assert _lvl0(doc, bullet).find(qn("w:suff")).get(qn("w:val")) == "nothing"
    assert _ind(bullet) == {"left": "540", "hanging": "0"}


def test_none_flush_drops_the_indent_and_the_tab(build):
    doc, _p, _o = build("none_flush")
    bullet = _tagged(doc, template_tags.BULLET_TAG)[0]
    assert _marker(doc, bullet) == ""
    assert _lvl0(doc, bullet).find(qn("w:suff")).get(qn("w:val")) == "nothing"
    assert _ind(bullet) == {"left": "0", "hanging": "0"}


def test_skills_get_a_marker_of_their_own_with_the_lists_indent(build):
    keep, _p, _o = build(name="keep.docx")
    skills = _tagged(keep, template_tags.SKILLS_LABEL_TAG)[0]
    assert template_bullets._paragraph_num_id(skills) is None
    doc, _p, _o = build("keep", "–")
    skills = _tagged(doc, template_tags.SKILLS_LABEL_TAG)[0]
    bullet = _tagged(doc, template_tags.BULLET_TAG)[0]
    assert _marker(doc, skills) == "–"
    assert _marker(doc, bullet) is None
    assert _ind(skills) == _ind(bullet)


def test_none_survives_the_layout_file_and_a_glyph_brings_bullets_back(build, tmp_path):
    doc, profile, tagged = build("none_flush")
    sk = template_skeleton.make_skeleton(tagged, profile, synthetic_resume())
    parsed = skeleton_parse.parse_skeleton(sk.raw, sk.meta())
    assert parsed.result.ready, parsed.result.issues
    realised = tmp_path / "realised.docx"
    realised.write_bytes(parsed.raw)
    again, _p, _o = build(
        "•", source=realised, profile=parsed.result.suggested_profile, name="again.docx"
    )
    bullet = _tagged(again, template_tags.BULLET_TAG)[0]
    assert _marker(again, bullet) == "•"
    assert _lvl0(again, bullet).find(qn("w:suff")) is None
    assert _ind(bullet) == {"left": "540", "hanging": "360"}
