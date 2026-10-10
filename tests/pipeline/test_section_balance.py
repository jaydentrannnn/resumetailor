"""Section balance: per-section relative weights (`fit_selection._section_pools`)."""

import pytest

from resume_tailor.content.data import (
    Bullet,
    Experience,
    ExperienceSection,
    MasterResume,
    Project,
    ProjectSection,
)
from resume_tailor.pipeline import fit_selection, selection
from resume_tailor.pipeline.jd import JobRequirements, Keyword


def _job(eid: str, n: int) -> Experience:
    return Experience(
        id=eid, company=eid, title="Engineer", start="2024-01", end="Present",
        bullets=[Bullet(id=f"{eid}{i}", text=f"Built {eid}{i}.", tags=["python"]) for i in range(n)],
    )


def _project(pid: str, n: int) -> Project:
    return Project(
        id=pid, name=pid,
        bullets=[Bullet(id=f"{pid}{i}", text=f"Made {pid}{i}.", tags=["python"]) for i in range(n)],
    )


@pytest.fixture
def resume() -> MasterResume:
    return MasterResume(
        contact={"name": "Ada", "email": "a@x.com"},
        sections=[
            ExperienceSection(id="work", title="Work", entries=[_job("w", 10)]),
            ExperienceSection(id="research", title="Research", entries=[_job("r", 10)]),
            ProjectSection(id="projects", title="Projects", entries=[_project("p", 10)]),
        ],
    )


def _entries(resume: MasterResume) -> list:
    return [e for s in resume.entry_sections for e in s.entries]


def _reqs() -> JobRequirements:
    return JobRequirements(
        title="Engineer", seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _budgets(resume, entries, weights, limit=8) -> dict[str, int]:
    pools, shares = fit_selection._section_pools(resume, entries, None, weights)
    chosen = selection.select_within_entries(
        entries, _reqs(), limit=limit, pools=pools, weights=shares,
    )
    counts = {"w": 0, "r": 0, "p": 0}
    for bullet in chosen:
        counts[bullet.id[0]] += 1
    return counts


def test_relative_weights_become_shares_of_the_total(resume):
    _, shares = fit_selection._section_pools(
        resume, _entries(resume), None, {"work": 2, "research": 1, "projects": 1}
    )
    assert shares == [0.5, 0.25, 0.25]
    assert _budgets(resume, _entries(resume), {"work": 2, "research": 1, "projects": 1}) == {
        "w": 4, "r": 2, "p": 2,
    }


def test_a_section_missing_from_the_weights_gets_the_mean(resume):
    _, shares = fit_selection._section_pools(
        resume, _entries(resume), None, {"work": 3, "research": 1}
    )
    assert shares == pytest.approx([0.5, 1 / 6, 2 / 6])


def test_a_section_with_no_chosen_entries_drops_out_and_the_rest_renormalise(resume):
    entries = [e for e in _entries(resume) if e.id != "r"]
    _, shares = fit_selection._section_pools(
        resume, entries, None, {"work": 3, "research": 5, "projects": 1}
    )
    assert shares == [0.75, None, 0.25]
    assert _budgets(resume, entries, {"work": 3, "research": 5, "projects": 1}) == {
        "w": 6, "r": 0, "p": 2,
    }


def test_the_one_bullet_floor_beats_a_zero_weight(resume):
    # The floors are hard minimums on top of the weighted shares (`_allocate_budgets`).
    assert _budgets(resume, _entries(resume), {"work": 1, "research": 0, "projects": 0}) == {
        "w": 8, "r": 1, "p": 1,
    }


def test_section_weights_beat_the_legacy_experience_share(resume):
    _, shares = fit_selection._section_pools(
        resume, _entries(resume), 0.9, {"work": 1, "research": 1, "projects": 2}
    )
    assert shares == [0.25, 0.25, 0.5]


def test_legacy_share_is_unchanged_without_section_weights(resume):
    _, shares = fit_selection._section_pools(resume, _entries(resume), 0.6, None)
    assert shares == pytest.approx([0.3, 0.3, 0.4])
    assert fit_selection._section_pools(resume, _entries(resume), None, None) == (None, None)
