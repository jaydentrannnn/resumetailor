"""Computed bullet tags: detection, the run annotation, and which layer reaches where."""

from __future__ import annotations

from resume_tailor.content import bullet_tags
from resume_tailor.content.data import Bullet, MasterResume
from resume_tailor.pipeline import fabrication, selection, skills
from resume_tailor.pipeline.jd import JobRequirements, Keyword


def _resume(*bullets: dict, skills_items=(), tech=()) -> MasterResume:
    return MasterResume.model_validate(
        {
            "contact": {"name": "T", "email": "t@example.com"},
            "education": [],
            "experience": [
                {"company": "Acme", "title": "Analyst", "start": "2020", "end": "2021",
                 "bullets": list(bullets)}
            ],
            "projects": [{"id": "p", "name": "P", "tech": list(tech), "bullets": []}] if tech else [],
            "skills": [{"label": "Tools", "items": list(skills_items)}] if skills_items else [],
        }
    )


def _bullet(text: str, *tags: str, bid: str = "b1") -> dict:
    return {"id": bid, "text": text, "tags": list(tags)}


def _reqs(*canonicals: str) -> JobRequirements:
    return JobRequirements(
        title="T",
        seniority="entry",
        keywords=[Keyword(phrase=c, canonical=c, importance="must_have") for c in canonicals],
    )


def test_detects_dictionary_terms_and_spellings_with_their_surface_text():
    found = bullet_tags.detect("Built DCF models in Excel and a Postgres ETL")
    assert found == [
        ("discounted cash flow", "DCF"),
        ("excel", "Excel"),
        ("postgresql", "Postgres"),
    ]


def test_longer_phrases_win_and_words_inside_words_never_match():
    assert [c for c, _ in bullet_tags.detect("Applied machine learning to pythonic code")] == [
        "machine learning"
    ]


def test_short_names_and_ordinary_words_need_capitals():
    assert bullet_tags.detect("Covered the rest of the lean team; trained an ml model") == []
    found = [c for c, _ in bullet_tags.detect("Shipped a REST API with ML ranking on a Lean team")]
    assert found == ["rest", "machine learning", "lean"]


def test_the_resumes_own_skills_and_tech_count_as_terms():
    resume = _resume(
        _bullet("Charted wards with Epic and triaged in Pyxis"),
        skills_items=("Epic",),
        tech=("Pyxis",),
    )
    assert bullet_tags.known_terms(resume) == ["epic", "pyxis"]


def test_match_tags_union_extra_skills_detected_and_inferred():
    resume = _resume(_bullet("Built DCF models", "Valuation"))
    bullet = resume.all_bullets()[0]
    assert bullet_tags.match_tags(bullet) == {"discounted cash flow", "valuation"}

    bullet_tags.annotate(resume, {"Built DCF models": ["Financial Modeling"]})
    assert "financial modeling" in bullet_tags.match_tags(bullet)
    assert "financial modeling" not in bullet_tags.match_tags(bullet, inferred=False)
    assert "financial modeling" in bullet_tags.known_terms(resume)


def test_selection_scores_a_detected_skill_with_no_tags_at_all():
    bullet = Bullet(id="b1", text="Tuned PostgreSQL queries")
    assert bullet.tags == []
    assert selection._keyword_score(bullet, _reqs("postgresql")) > 0


def test_inferred_skills_never_reach_the_skills_pool_or_the_whitelist():
    resume = _resume(_bullet("Built DCF models in Excel"))
    bullet_tags.annotate(resume, {"Built DCF models in Excel": ["Tableau"]})
    bullet = resume.all_bullets()[0]

    assert "tableau" in bullet_tags.match_tags(bullet)
    labels = [c.label for c in skills.build_pool(resume, _reqs("tableau"))]
    assert "Tableau" not in labels and "tableau" not in labels
    assert "DCF" in labels  # detected, by its surface text, never the expansion
    assert "Tableau" in fabrication.check_fabrication(bullet, "Built DCF models in Tableau")


def test_extra_skills_still_extend_the_whitelist():
    bullet = Bullet(id="b1", text="Built dashboards", tags=["Tableau"])
    assert "Tableau" not in fabrication.check_fabrication(bullet, "Built Tableau dashboards")
