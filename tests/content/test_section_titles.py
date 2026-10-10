"""`section_titles.sync_titles`: template heading text becomes the resume's section titles."""

from __future__ import annotations

from resume_tailor.content import section_titles
from resume_tailor.content.data import ExperienceSection
from resume_tailor.document.template_profile import DetectedSection
from tests.fixtures import synthetic_resume


def _detected(*pairs):
    return [
        DetectedSection(id=f"s{i}", title=title, kind=kind, heading_paragraph_id=i)
        for i, (title, kind) in enumerate(pairs)
    ]


def test_titles_pair_by_kind_and_order():
    resume = synthetic_resume()
    resume.sections.append(ExperienceSection(id="lead", title="Leadership", entries=[]))
    detected = _detected(
        ("WORK EXPERIENCE", "experience"),
        ("Leadership & Service", "experience"),
        ("Technical Skills", "skills"),
    )

    synced, changes = section_titles.sync_titles(resume, detected)

    titles = {s.id: s.title for s in synced.sections}
    experience = [s for s in synced.sections if s.kind == "experience"]
    assert [s.title for s in experience] == ["WORK EXPERIENCE", "Leadership & Service"]
    assert [s.title for s in synced.sections if s.kind == "skills"] == ["Technical Skills"]
    # Kinds the template has no heading for keep their title.
    assert [s.title for s in synced.sections if s.kind == "project"] == ["PROJECTS"]
    assert ("Leadership", "Leadership & Service") in changes
    assert len(changes) == 3
    # The input is never mutated.
    assert {s.id: s.title for s in resume.sections} != titles


def test_matching_titles_report_no_changes():
    resume = synthetic_resume()
    detected = _detected(*[(s.title, s.kind) for s in resume.sections])
    synced, changes = section_titles.sync_titles(resume, detected)
    assert changes == []
    assert synced == resume
