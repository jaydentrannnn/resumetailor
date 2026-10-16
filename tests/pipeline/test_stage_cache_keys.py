"""Each cached stage keys on everything its prompt shows: an edit there is a cache miss."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.pipeline import coverletter, expand, facets, skills
from resume_tailor.pipeline.jd import JobRequirements, Keyword
from tests.fixtures import synthetic_resume


def _reqs() -> JobRequirements:
    return JobRequirements(
        title="Engineer", seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def test_expansion_key_covers_permitted_skills():
    resume = synthetic_resume()
    entry = resume.experience[0]
    keyed = [(expand.entry_key(entry.id), entry)]
    before = expand._cache_path(keyed, _reqs(), char_limit=2000)
    entry.bullets[0].tags = [*entry.bullets[0].tags, "kubernetes"]
    assert expand._cache_path(keyed, _reqs(), char_limit=2000) != before


def test_skills_key_covers_bullet_counts():
    one = [skills.SkillCandidate("python", "Python", ("tag",), bullet_count=1)]
    three = [skills.SkillCandidate("python", "Python", ("tag",), bullet_count=3)]
    assert skills._cache_path(one, _reqs(), limit=20) != skills._cache_path(three, _reqs(), limit=20)


def test_cover_letter_key_covers_education_skills_and_headers():
    resume = synthetic_resume()
    bullets = {b.id: b.text for b in resume.all_bullets()}

    def key(r):
        return coverletter._cache_path(
            bullets, _reqs(), jd_text="Python role.", word_band=(250, 350), resume=r
        )

    base = key(resume)
    for edit in (
        lambda r: setattr(r.education[0], "degree", "B.A. History"),
        lambda r: setattr(r.skills[0], "items", ["Fortran"]),
        lambda r: setattr(r.experience[0], "company", "Other Co"),
    ):
        changed = synthetic_resume()
        edit(changed)
        assert key(changed) != base


def test_facets_key_covers_project_names_and_limits(monkeypatch):
    resume = synthetic_resume()
    base = facets._cache_path(resume, _reqs())
    renamed = synthetic_resume()
    renamed.projects[0].name = "Another Project"
    assert facets._cache_path(renamed, _reqs()) != base
    monkeypatch.setattr(config, "MAX_PROJECT_TECH", config.MAX_PROJECT_TECH + 1)
    assert facets._cache_path(resume, _reqs()) != base
