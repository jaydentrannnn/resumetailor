"""Coverage-aware bullet selection: a keyword already shown is worth less to the next pick."""

import pytest

from resume_tailor import config
from resume_tailor.content.data import Bullet, Experience
from resume_tailor.pipeline import selection
from resume_tailor.pipeline.jd import JobRequirements, Keyword


def _job(name: str, bullets: list[tuple[str, list[str]]]) -> Experience:
    return Experience(
        id=name, company=name, title="Engineer", start="2024-01", end="Present",
        bullets=[Bullet(id=bid, text=f"Built {bid}.", tags=tags) for bid, tags in bullets],
    )


def _reqs() -> JobRequirements:
    return JobRequirements(
        title="Engineer",
        seniority="entry",
        keywords=[
            Keyword(phrase="Python", canonical="python", importance="must_have"),
            Keyword(phrase="SQL", canonical="sql", importance="must_have"),
            Keyword(phrase="Kubernetes", canonical="kubernetes", importance="must_have"),
        ],
    )


@pytest.fixture
def entries() -> list[Experience]:
    # Four Python+SQL bullets edge out the lone Kubernetes bullet on raw score.
    return [_job("a", [
        ("py1", ["python", "sql"]), ("py2", ["python", "sql"]), ("py3", ["python", "sql"]),
        ("py4", ["python", "sql"]), ("k8s", ["kubernetes"]),
    ])]


def _picked(entries, limit: int) -> set[str]:
    chosen = selection.select_within_entries(entries, _reqs(), limit=limit)
    return {b.id for b in chosen}


def test_off_by_default_ranks_on_raw_score(entries):
    assert config.COVERAGE_SELECTION is False
    assert _picked(entries, 3) == {"py1", "py2", "py3"}


def test_coverage_picks_the_unshown_must_have(entries, monkeypatch):
    monkeypatch.setattr(config, "COVERAGE_SELECTION", True)
    # py1 (floor) and py2 show Python and SQL twice; a third copy is worth nothing,
    # so Kubernetes takes the last slot.
    assert _picked(entries, 3) == {"py1", "py2", "k8s"}


def test_coverage_still_fills_every_slot(entries, monkeypatch):
    monkeypatch.setattr(config, "COVERAGE_SELECTION", True)
    assert _picked(entries, 5) == {"py1", "py2", "py3", "py4", "k8s"}


def test_coverage_is_shared_across_section_pools(monkeypatch):
    monkeypatch.setattr(config, "COVERAGE_SELECTION", True)
    jobs = _job("job", [("j1", ["python"]), ("j2", ["python"])])
    projects = _job("proj", [("p1", ["python"]), ("p2", ["python"]), ("p3", ["sql"])])
    chosen = selection.select_within_entries(
        [jobs, projects], _reqs(), limit=4, pools=[[jobs], [projects]], weights=[0.5, 0.5],
    )
    # The job pool already shows Python twice, so the project pool's second pick is SQL.
    assert {b.id for b in chosen} == {"j1", "j2", "p1", "p3"}
