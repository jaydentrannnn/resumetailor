"""Templates with no Experience section (B16): a first-year student's Education +
Projects resume analyzes, builds and renders; Education alone still blocks.
"""

from __future__ import annotations

import zipfile

import pytest

from resume_tailor.document import render, template_analyze, template_build
from resume_tailor.document.template_profile import EnabledSections, TemplateProfile
from tests.fixtures import _docx_bytes, _full_featured_resume, synthetic_resume


def _drop_between(document, start_text: str, stop_text: str) -> None:
    body = document.element.body
    removing = False
    for paragraph in list(document.paragraphs):
        if paragraph.text == start_text:
            removing = True
        elif paragraph.text == stop_text:
            removing = False
        if removing:
            body.remove(paragraph._p)


def _no_experience(document) -> None:
    _full_featured_resume(document)
    _drop_between(document, "WORK EXPERIENCES", "PROJECTS")


def _education_only(document) -> None:
    _full_featured_resume(document)
    _drop_between(document, "WORK EXPERIENCES", "SKILLS")


def test_projects_without_experience_is_ready():
    result = template_analyze.analyze_docx(raw=_docx_bytes(_no_experience))
    issues = {issue.code: issue for issue in result.issues}
    assert issues["missing_experience"].blocking is False
    assert result.ready, result.issues
    profile = result.suggested_profile
    assert profile.enabled.experience is False and profile.experience is None
    assert profile.enabled.projects is True


def test_education_only_still_blocks():
    result = template_analyze.analyze_docx(raw=_docx_bytes(_education_only))
    blocking = {issue.code for issue in result.issues if issue.blocking}
    assert "missing_experience" in blocking
    assert not result.ready


def test_builds_and_renders_without_experience(tmp_path):
    src = tmp_path / "original_export.docx"
    src.write_bytes(_docx_bytes(_no_experience))
    result = template_analyze.analyze_docx(raw=src.read_bytes())
    built = tmp_path / "main_template.docx"
    template_build.build_from_profile(src, built, result.suggested_profile)
    out = tmp_path / "out.docx"
    render.render(synthetic_resume(), template=built, out=out)
    with zipfile.ZipFile(out) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Note Engine" in xml  # the project renders
    assert "State University" in xml
    assert "Example Corp" not in xml  # nowhere to put experience; not an error
    assert "{{" not in xml and "{%" not in xml


def test_profile_needs_some_entry_section():
    base = template_analyze.analyze_docx(raw=_docx_bytes(_no_experience)).suggested_profile
    data = base.model_dump()
    data["enabled"] = EnabledSections(
        experience=False, projects=False, education=True, skills=True, list_section=False
    ).model_dump()
    data["projects"] = None
    with pytest.raises(ValueError, match="Experience, Projects or list"):
        TemplateProfile.model_validate(data)


@pytest.mark.parametrize("section_mode", ["fixed", "generic"])
def test_fit_skips_experience_when_template_has_none(section_mode):
    from resume_tailor.pipeline import fit
    from resume_tailor.pipeline.jd import JobRequirements, Keyword

    resume = synthetic_resume()
    requirements = JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    with_exp = {"section_mode": section_mode, "enabled": {"experience": True}}
    without = {"section_mode": section_mode, "enabled": {"experience": False}}
    exp_ids = {s.id for s in resume.entry_sections if s.kind == "experience"}

    chosen = fit.choose_entries(
        resume, requirements, layout=without, section_limits={i: 5 for i in exp_ids}
    )
    assert not any(isinstance(e, type(resume.experience[0])) for e in chosen)
    assert any(isinstance(e, type(resume.projects[0])) for e in chosen)

    bullets = {b.id: b.text for b in resume.all_bullets()}
    assert fit.estimate_lines(resume, bullets, layout=without) < fit.estimate_lines(
        resume, bullets, layout=with_exp
    )
