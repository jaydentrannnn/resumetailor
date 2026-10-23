"""An accepted evidence item written into the resume (`content/evidence_accept.py`)."""

from __future__ import annotations

import pytest
from fixtures import synthetic_resume

from resume_tailor.content import evidence_accept
from resume_tailor.content.evidence_accept import AcceptError, AddRequest
from resume_tailor.content.evidence_store import NewProject, Proposal


def _proposal(kind: str, text: str, target: str = "", project: NewProject | None = None) -> Proposal:
    return Proposal(id="e1", source_id="s1", kind=kind, target_entry_id=target, text=text,
                    excerpt="x" * 20, basis="stated", new_project=project)


def test_a_bullet_gets_the_next_id_in_its_entry_and_only_the_ticked_skills():
    resume = synthetic_resume()
    saved, where = evidence_accept.add(
        resume, _proposal("bullet", "Shipped a parser", "example-corp"),
        AddRequest(text="  Shipped a  streaming parser ", skills=["Rust"]),
    )
    entry = next(e for e in saved.experience if e.id == "example-corp")
    assert where == "bullet exp_b2"
    assert (entry.bullets[-1].id, entry.bullets[-1].text, entry.bullets[-1].tags) == (
        "exp_b2", "Shipped a streaming parser", ["Rust"],
    )
    assert len(resume.experience[0].bullets) == 1  # the input is untouched


def test_a_bullet_can_go_to_another_entry_than_proposed():
    saved, where = evidence_accept.add(
        synthetic_resume(), _proposal("bullet", "Added search", "example-corp"),
        AddRequest(text="Added search", target_entry_id="note-engine"),
    )
    assert where == "bullet proj_b2"
    assert saved.projects[0].bullets[-1].text == "Added search"


def test_a_new_project_lands_in_the_project_section_with_its_first_bullet():
    project = NewProject(name="Fridge Chef", tech=["Flask", "PyTorch"], url="https://github.com/j/fc",
                         start="2025-01", end="2025-03")
    saved, where = evidence_accept.add(
        synthetic_resume(), _proposal("project", "Built a recipe recommender", project=project),
        AddRequest(text="Built a recipe recommender"),
    )
    added = next(p for p in saved.projects if p.name == "Fridge Chef")
    assert where == "project proj_fridge-chef"
    assert (added.tech, added.start, added.bullets[0].id) == (
        ["Flask", "PyTorch"], "2025-01", "proj_fridge-chef_b1",
    )


def test_skills_and_courses_join_the_group_and_school_picked_without_repeats():
    resume = synthetic_resume()
    saved, where = evidence_accept.add(
        resume, _proposal("skill", "Docker", "example-corp"),
        AddRequest(text="Docker", skill_group="Tools"),
    )
    assert where == "skills Tools" and saved.skills[0].items[-1] == "Docker"
    again, _ = evidence_accept.add(saved, _proposal("skill", "docker"), AddRequest(text="docker", skill_group="Tools"))
    assert [i.casefold() for i in again.skills[0].items].count("docker") == 1

    saved, where = evidence_accept.add(
        resume, _proposal("coursework", "Operating Systems"), AddRequest(text="Operating Systems"),
    )
    assert where == "coursework State University"
    assert saved.education[0].coursework[-1] == "Operating Systems"


@pytest.mark.parametrize(("proposal", "request_", "message"), [
    (_proposal("bullet", "x", "gone"), AddRequest(text="x"), "no longer exists"),
    (_proposal("project", "x"), AddRequest(text="x"), "Give the project a name"),
    (_proposal("skill", "Docker"), AddRequest(text="Docker", skill_group="Nope"), "Skills group"),
    (_proposal("coursework", "OS"), AddRequest(text="OS", education_index=3), "school"),
])
def test_an_unplaceable_item_says_what_to_pick(proposal, request_, message):
    with pytest.raises(AcceptError, match=message):
        evidence_accept.add(synthetic_resume(), proposal, request_)


def test_a_project_needs_a_project_section():
    resume = synthetic_resume()
    resume.sections = [s for s in resume.sections if s.kind != "project"]
    with pytest.raises(AcceptError, match="Projects section"):
        evidence_accept.add(resume, _proposal("project", "x", project=NewProject(name="P")),
                            AddRequest(text="Built P"))
