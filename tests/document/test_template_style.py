"""Template style: separators the renderer writes and the link look, defaulting to the
output from before the settings existed, and kept through a layout-file round trip."""

from __future__ import annotations

import io

import docx
import pytest
from docx.oxml.ns import qn
from pydantic import ValidationError

from resume_tailor import config
from resume_tailor.document import (
    docx_text,
    render,
    skeleton_parse,
    template_analyze,
    template_build,
    template_skeleton,
    template_style,
)
from resume_tailor.document.template_profile import active_layout
from resume_tailor.document.template_style import Links, Separators, TemplateStyle
from tests.fixtures import _docx_bytes, _full_featured_resume, synthetic_resume


@pytest.fixture
def built(tmp_path, monkeypatch):
    raw = _docx_bytes(_full_featured_resume)
    profile = template_analyze.analyze_docx(raw=raw).suggested_profile
    src, tpl = tmp_path / "baseline.docx", tmp_path / "tagged.docx"
    src.write_bytes(raw)
    monkeypatch.setattr(config, "BASELINE_TEMPLATE_PATH", src)
    template_build.build_from_profile(src, tpl, profile)
    return profile, tpl


def _render(tmp_path, profile, tpl, style: TemplateStyle | None = None, name="out.docx"):
    if style is not None:
        profile = profile.model_copy(update={"style": style})
    out = tmp_path / name
    render.render(synthetic_resume(), template=tpl, out=out, layout=active_layout(profile))
    return docx.Document(str(out))


def _texts(doc) -> list[str]:
    return [p.text for p, _loc in docx_text.iter_document_paragraphs(doc)]


def _link_rpr(doc, text: str):
    for paragraph, _loc in docx_text.iter_document_paragraphs(doc):
        for link in paragraph._p.iter(qn("w:hyperlink")):
            if "".join(t.text or "" for t in link.iter(qn("w:t"))) == text:
                return link.find(f"{qn('w:r')}/{qn('w:rPr')}")
    raise AssertionError(f"no link {text!r}")


def test_default_style_leaves_layout_and_output_unchanged(tmp_path, built):
    profile, tpl = built
    assert "style" not in active_layout(profile)
    assert template_style.from_layout(active_layout(profile)) == template_style.DEFAULT
    texts = _texts(_render(tmp_path, profile, tpl))
    assert any("Python, FastAPI | Repo" in t for t in texts)
    assert any("Python, Data & Analytics" in t for t in texts)
    assert any(t.endswith("Algorithms, Databases") for t in texts)
    rpr = _link_rpr(_render(tmp_path, profile, tpl, name="b.docx"), "Repo")
    assert rpr.find(qn("w:color")).get(qn("w:val")) == "0000EE"
    assert rpr.find(qn("w:u")).get(qn("w:val")) == "single"


def test_separators_reach_every_line_that_prints_them(tmp_path, built):
    profile, tpl = built
    style = TemplateStyle(separators=Separators(
        tech_items=" · ", project_link=" – ", skills_items=" / ", coursework="; ",
        dates=" – ",
    ))  # fmt: skip
    texts = _texts(_render(tmp_path, profile, tpl, style))
    assert any("Python · FastAPI – Repo" in t for t in texts)
    assert any("Python / Data & Analytics" in t for t in texts)
    assert any(t.endswith("Algorithms; Databases") for t in texts)
    assert any("Jan 2023 – present" in t for t in texts)


def test_link_look_text_colour_without_underline(tmp_path, built):
    profile, tpl = built
    style = TemplateStyle(links=Links(color="text", underline=False))
    doc = _render(tmp_path, profile, tpl, style)
    for label in ("Repo", "LinkedIn"):
        rpr = _link_rpr(doc, label)
        assert rpr.find(qn("w:rStyle")).get(qn("w:val")) == "InternetLink"
        assert rpr.find(qn("w:color")).get(qn("w:val")) == "auto"
        assert rpr.find(qn("w:u")).get(qn("w:val")) == "none"


def test_style_survives_a_layout_file_round_trip(built):
    profile, tpl = built
    style = TemplateStyle(separators=Separators(tech_items=" / "), links=Links(underline=False))
    profile = profile.model_copy(update={"style": style})
    sk = template_skeleton.make_skeleton(tpl, profile, synthetic_resume())
    parsed = skeleton_parse.parse_skeleton(sk.raw, sk.meta())
    assert parsed.result.ready, parsed.result.issues
    assert parsed.result.suggested_profile.style == style


def test_unwrapped_link_runs_lose_the_link_look(built):
    profile, tpl = built
    sk = template_skeleton.make_skeleton(tpl, profile, synthetic_resume())
    body = docx.Document(io.BytesIO(sk.raw)).element.body
    for rpr in body.iter(qn("w:rPr")):
        color = rpr.find(qn("w:color"))
        assert color is None or color.get(qn("w:val")) != "0000EE"


@pytest.mark.parametrize("bad", ["", "abc", " |  |  | ", "\t"])
def test_separators_reject_text_that_is_not_punctuation(bad):
    with pytest.raises(ValidationError):
        Separators(tech_items=bad)


def test_a_template_without_a_link_slot_still_prints_project_links(tmp_path, monkeypatch):
    from resume_tailor.document import template_profile

    raw = _docx_bytes(_full_featured_resume)
    profile = template_analyze.analyze_docx(raw=raw).suggested_profile
    profile = profile.model_copy(update={"projects": profile.projects.model_copy(
        update={"link": template_profile.OptionalSpan(present=False)},
    )})  # fmt: skip
    src, tpl = tmp_path / "baseline.docx", tmp_path / "tagged.docx"
    src.write_bytes(raw)
    monkeypatch.setattr(config, "BASELINE_TEMPLATE_PATH", src)
    template_build.build_from_profile(src, tpl, profile)
    texts = _texts(_render(tmp_path, profile, tpl))
    line = next(t for t in texts if t.startswith("Note Engine"))
    assert line.split("\t")[0] == "Note Engine | Python, FastAPI | Repo"
    assert line.endswith("\t2024")


def test_the_link_separator_defaults_to_the_name_to_tools_gap():
    from types import SimpleNamespace

    from resume_tailor.document.template_analyze import _link_style
    from resume_tailor.document.template_profile import (
        CharSpan,
        HeaderFieldMapping,
        OptionalSpan,
        ProjectsMapping,
    )

    def mapping(link: bool) -> ProjectsMapping:
        return ProjectsMapping(
            heading_paragraph_id=0, heading_text="PROJECTS", prototype_entry_start=1,
            bullet_paragraph_id=2,
            header=HeaderFieldMapping(header_paragraph_id=1, fields={
                "name": OptionalSpan(span=CharSpan(paragraph_id=1, start=0, end=4)),
                "tech": OptionalSpan(span=CharSpan(paragraph_id=1, start=7, end=13)),
            }),
            link=OptionalSpan(span=CharSpan(paragraph_id=1, start=14, end=18))
            if link else OptionalSpan(present=False),
        )  # fmt: skip

    paras = [SimpleNamespace(text=""), SimpleNamespace(text="Name \u2013 Python Repo"), None]
    assert _link_style(mapping(False), paras).separators.project_link == " \u2013 "
    assert _link_style(mapping(True), paras) == template_style.DEFAULT
    paras[1] = SimpleNamespace(text="Name with Python")
    assert _link_style(mapping(False), paras) == template_style.DEFAULT
