"""Soft-skill must-haves match related tags (`config.SOFT_SKILL_RELATED_TAGS`)."""

from __future__ import annotations

from resume_tailor import config
from resume_tailor.content.data import Bullet
from resume_tailor.pipeline import selection
from resume_tailor.pipeline.jd import JobRequirements, Keyword


def _requirements(*keywords: Keyword) -> JobRequirements:
    return JobRequirements(title="Engineer", seniority="intern", keywords=list(keywords))


TEAMWORK = Keyword(phrase="multi-disciplinary teams", canonical="teamwork",
                   importance="must_have", kind="soft")


def test_a_leadership_bullet_counts_for_a_teamwork_must_have():
    led = Bullet(id="a", text="Led a 3-person team.", tags=["leadership"])
    assert selection.score(led, _requirements(TEAMWORK)) == config.SOFT_SKILL_WEIGHT


def test_a_soft_keyword_counts_once_however_many_related_tags_match():
    both = Bullet(id="a", text="Led a team.", tags=["leadership", "teamwork", "collaboration"])
    assert selection.score(both, _requirements(TEAMWORK)) == config.SOFT_SKILL_WEIGHT


def test_related_tags_never_satisfy_a_technical_keyword():
    tech = Keyword(phrase="leadership APIs", canonical="teamwork", importance="must_have",
                   kind="technical")
    led = Bullet(id="a", text="Led a team.", tags=["leadership"])
    assert selection.score(led, _requirements(tech)) == 0.0


def test_unrelated_soft_keywords_do_not_widen():
    detail = Keyword(phrase="attention to detail", canonical="attention to detail",
                     importance="must_have", kind="soft")
    led = Bullet(id="a", text="Led a team.", tags=["leadership"])
    assert selection.score(led, _requirements(detail)) == 0.0
