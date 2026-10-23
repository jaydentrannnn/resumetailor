"""Skill-gap insights over pursued applications (`skill_gaps.skill_gaps`)."""

from __future__ import annotations

from resume_tailor.apply.funnel import skill_gaps, store_models
from resume_tailor.pipeline.coverage import CoverageFunnel, KeywordCoverage


def _app(key: str, status: str, job_id: str | None = None, at: str = "t1", **extra):
    return store_models.Application(
        source="t", source_job_id=key, company=f"Co {key}", role="Analyst", status=status,
        job_id=job_id, status_history=[store_models.StatusChange(status=status, at=at)],
        **extra,
    )


def _funnel(*keywords: tuple[str, str | None, str | None]) -> CoverageFunnel:
    kws = [KeywordCoverage(c, c.title(), resume, page) for c, resume, page in keywords]
    return CoverageFunnel(total=len(kws), in_resume=sum(k.resume is not None for k in kws),
                          on_page=0, keywords=kws)


def _reader(funnels: dict[str, CoverageFunnel]):
    return lambda out_dir: funnels.get(out_dir.name)


def test_gaps_rank_by_near_miss_weight_not_raw_count():
    funnels = {
        # Two far-off postings ask for Go: 0/2 backed each, so weight 0.
        "j1": _funnel(("go", None, None), ("rust", None, None)),
        "j2": _funnel(("go", None, None), ("rust", None, None)),
        # One near-miss asks for Tableau: 3 of 4 backed.
        "j3": _funnel(("tableau", None, None), ("sql", "stated", "expressed"),
                      ("python", "stated", "expressed"), ("excel", "stated", "expressed")),
    }
    rows = [_app(k, "submitted", job_id=k) for k in funnels]
    result = skill_gaps.skill_gaps(rows, read=_reader(funnels))
    assert [g.canonical for g in result.gaps] == ["tableau", "go", "rust"]
    assert (result.gaps[0].weight, result.gaps[0].jobs) == (0.75, 1)
    assert result.gaps[1].jobs == 2 and result.counted == 3


def test_not_shown_is_listed_apart_and_page_hits_are_neither():
    funnels = {"j1": _funnel(("sql", "stated", "expressed"), ("tableau", "tagged", "tag_only"),
                             ("excel", "stated", "not_selected"))}
    result = skill_gaps.skill_gaps([_app("a", "ready", job_id="j1")], read=_reader(funnels))
    assert result.gaps == []
    assert [g.canonical for g in result.not_shown] == ["excel", "tableau"]
    assert result.not_shown[0].companies == ["Co a"]


def test_only_pursued_rows_count_once_per_run():
    funnels = {"j1": _funnel(("go", None, None)), "j2": _funnel(("go", None, None))}
    rows = [
        _app("a", "submitted", job_id="j1"),
        _app("b", "interview", job_id="j1"),  # the same run, reused
        _app("c", "screened_out", job_id="j2"),
        _app("d", "submitted", job_id="j2", duplicate_of="a"),
        _app("e", "screened_in"),  # pursued, never tailored
    ]
    result = skill_gaps.skill_gaps(rows, read=_reader(funnels))
    assert (result.counted, result.uncounted, result.gaps[0].jobs) == (1, 1, 1)


def test_a_gap_the_resume_backs_since_drops_out():
    funnels = {"j1": _funnel(("go", None, None), ("rust", None, None))}
    rows = [_app("a", "submitted", job_id="j1")]
    result = skill_gaps.skill_gaps(rows, known={"go"}, read=_reader(funnels))
    assert [g.canonical for g in result.gaps] == ["rust"]


def test_most_used_phrase_names_the_skill_and_companies_newest_first():
    def funnel(phrase: str) -> CoverageFunnel:
        return CoverageFunnel(total=1, in_resume=0, on_page=0,
                              keywords=[KeywordCoverage("ml", phrase, None, None)])

    funnels = {"j1": funnel("ML"), "j2": funnel("machine learning"),
               "j3": funnel("machine learning")}
    rows = [_app("a", "submitted", job_id="j1", at="2026-10-01"),
            _app("b", "submitted", job_id="j2", at="2026-10-03"),
            _app("c", "submitted", job_id="j3", at="2026-10-02")]
    [gap] = skill_gaps.skill_gaps(rows, read=_reader(funnels)).gaps
    assert gap.skill == "machine learning" and gap.companies == ["Co b", "Co c", "Co a"]
