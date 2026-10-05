"""Entry ranking rewards usable evidence, while rendering and section order stay stable."""

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet, Experience
from resume_tailor.pipeline import expand, selection
from resume_tailor.pipeline.jd import JobRequirements
from tests.fixtures import synthetic_resume


@pytest.fixture(autouse=True)
def no_default_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_BULLETS_PER_ENTRY", None)


def entry(name, scores):
    value = Experience(
        id=name,
        company=name,
        title="Engineer",
        start="2024-01",
        end="Present",
        bullets=[
            Bullet(id=f"{name}-{i}", text="Built a Python service.", tags=["python"])
            for i in range(len(scores))
        ],
    )
    return value, {b.id: s for b, s in zip(value.bullets, scores, strict=True)}


def reqs():
    return JobRequirements(title="Engineer", seniority="entry")


def test_short_strong_entry_beats_long_weak_entry():
    long, a = entry("long", [4] * 10)
    short, b = entry("short", [10, 9])
    assert selection.select_entries([long, short], reqs(), semantic={**a, **b}, limit=1) == [short]


def test_bullets_below_top_three_cannot_increase_rank():
    original, a = entry("original", [9, 8, 7])
    extended, b = entry("extended", [9, 8, 7, 6, 5, 4])
    assert selection.score_entry(original, reqs(), semantic=a) == selection.score_entry(
        extended, reqs(), semantic=b
    )


@pytest.mark.parametrize("cap,total", [(None, 24), (1, 9), (2, 17), (4, 24)])
def test_best_three_respects_tighter_cap(cap, total):
    value, scores = entry("job", [3, 8, 9, 7])
    assert selection.score_entry(
        value, reqs(), semantic=scores, max_per_entry=cap
    ) == total * config.SEMANTIC_WEIGHT * selection.entry_recency(value)


def test_short_entries_sum_without_padding_and_ties_preserve_source_order():
    first, a = entry("first", [9, 8])
    second, b = entry("second", [8, 9])
    assert selection.score_entry(
        first, reqs(), semantic=a
    ) == 17 * config.SEMANTIC_WEIGHT * selection.entry_recency(first)
    assert selection.select_entries([second, first], reqs(), semantic={**a, **b}, limit=1) == [
        second
    ]
    assert selection.select_entries([second, first], reqs(), semantic={**a, **b}, limit=2) == [
        second,
        first,
    ]


def test_profile_cap_is_used_when_no_per_run_override(monkeypatch):
    value, scores = entry("job", [9, 8, 7])
    monkeypatch.setattr(config, "MAX_BULLETS_PER_ENTRY", 1)
    assert selection.score_entry(
        value, reqs(), semantic=scores
    ) == 9 * config.SEMANTIC_WEIGHT * selection.entry_recency(value)
    assert selection.score_entry(
        value, reqs(), semantic=scores, max_per_entry=2
    ) > selection.score_entry(value, reqs(), semantic=scores)


def test_expansion_extras_use_same_cap_and_force_resume_entry():
    forced, a = entry("forced", [0])
    sharp, b = entry("sharp", [10, 0])
    broad, c = entry("broad", [9, 9])
    resume = synthetic_resume()
    section = resume.entry_sections[0]
    section.entries = [forced, sharp, broad]
    assert expand.choose_entries(
        resume,
        reqs(),
        resume_bullet_ids={forced.bullets[0].id},
        semantic={**a, **b, **c},
        limit=2,
        max_per_entry=1,
    ) == [forced, sharp]
    assert expand.choose_entries(
        resume,
        reqs(),
        resume_bullet_ids={forced.bullets[0].id},
        semantic={**a, **b, **c},
        limit=2,
        max_per_entry=2,
    ) == [forced, broad]
