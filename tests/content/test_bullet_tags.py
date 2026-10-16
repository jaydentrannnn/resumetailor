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
        ("etl", "ETL"),
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


def test_known_terms_with_explicit_inferred_skills_ignores_the_run_context():
    resume = _resume(_bullet("Wrote unit tests for the billing service"))
    bullet_tags.annotate(resume, {"Wrote unit tests for the billing service": ["mocking"]})

    explicit = bullet_tags.known_terms(
        resume, {"Wrote unit tests for the billing service": ["Load Testing"]}
    )

    assert "load testing" in explicit and "mocking" not in explicit
    assert "mocking" not in bullet_tags.known_terms(resume, {})
    # The installed context is read, never replaced, by an explicit call.
    assert "mocking" in bullet_tags.known_terms(resume)


def test_tool_names_that_are_ordinary_words_need_capitals():
    assert bullet_tags.detect("Shipped a swift rollout and a spark of interest") == []
    assert [c for c, _ in bullet_tags.detect("Built jobs in Spark and Swift")] == ["spark", "swift"]


def test_concurrent_runs_keep_their_own_annotation():
    """A second job's `prepare_run` (clear, then annotate) must not change what a job
    already selecting sees: each run's match-tag context lives in its run context."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from resume_tailor import config

    resume = _resume(_bullet("Built DCF models"))
    bullet = resume.all_bullets()[0]
    steps = [threading.Barrier(2) for _ in range(3)]

    def run_a() -> list[bool]:
        with config.use_context(config.default_context()):
            bullet_tags.annotate(resume, {"Built DCF models": ["Financial Modeling"]})
            seen = []
            for barrier in steps:
                barrier.wait(timeout=10)  # B clears, then installs its own inference
                tags = bullet_tags.match_tags(bullet)
                seen.append("financial modeling" in tags and "sql" not in tags)
            return seen

    def run_b() -> None:
        with config.use_context(config.default_context()):
            steps[0].wait(timeout=10)
            bullet_tags.clear()
            steps[1].wait(timeout=10)
            bullet_tags.annotate(resume, {"Built DCF models": ["SQL"]})
            steps[2].wait(timeout=10)
            assert "sql" in bullet_tags.match_tags(bullet)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(run_a), pool.submit(run_b)
        b.result(timeout=15)
        assert a.result(timeout=15) == [True, True, True]
    # Neither run touched the process fallback.
    assert "financial modeling" not in bullet_tags.match_tags(bullet)


def test_a_run_that_has_not_annotated_never_reads_the_process_fallback():
    """The fallback is whatever an earlier caller installed — maybe another resume's."""
    from resume_tailor import config

    resume = _resume(_bullet("Built DCF models"))
    bullet = resume.all_bullets()[0]
    bullet_tags.annotate(resume, {"Built DCF models": ["Financial Modeling"]})  # fallback
    try:
        assert "financial modeling" in bullet_tags.match_tags(bullet)
        with config.use_context(config.default_context()):
            assert "financial modeling" not in bullet_tags.match_tags(bullet)
            assert "financial modeling" not in bullet_tags.known_terms(resume)
    finally:
        bullet_tags.clear()


def test_a_thread_started_from_the_run_sees_its_annotation():
    """Background work (the in-run expansion) captures the run's context after
    `prepare_run`, so it reads the same match tags as the run itself."""
    import threading

    from resume_tailor import config

    resume = _resume(_bullet("Built DCF models"))
    bullet = resume.all_bullets()[0]
    seen: list[frozenset[str]] = []
    with config.use_context(config.default_context()):
        bullet_tags.annotate(resume, {"Built DCF models": ["Financial Modeling"]})
        worker = threading.Thread(
            target=config.run_in_context(lambda: seen.append(bullet_tags.match_tags(bullet)))
        )
        worker.start()
        worker.join(timeout=10)
    assert seen and "financial modeling" in seen[0]


def test_parallel_runs_compute_what_serial_runs_compute():
    """Deterministic stand-in for two tailoring jobs at once: each run installs its own
    resume's inference, then ranks bullets and builds its skill vocabulary repeatedly.
    Interleaved across threads, every result must equal the serial one."""
    from concurrent.futures import ThreadPoolExecutor

    from resume_tailor import config

    runs = {
        "a": (_resume(_bullet("Built DCF models", bid="a1"), _bullet("Ran Excel reports", bid="a2")),
              {"Built DCF models": ["Financial Modeling"], "Ran Excel reports": ["Reporting"]},
              _reqs("financial modeling", "reporting", "sql")),
        "b": (_resume(_bullet("Tuned SQL queries", bid="b1"), _bullet("Wrote Python ETL", bid="b2")),
              {"Tuned SQL queries": ["Database Optimization"], "Wrote Python ETL": ["Data Pipelines"]},
              _reqs("database optimization", "data pipelines", "python")),
    }

    def one_run(name: str) -> tuple:
        resume, inferred, reqs = runs[name]
        with config.use_context(config.default_context()):
            bullet_tags.clear()
            bullet_tags.annotate(resume, inferred)
            results = []
            for _ in range(25):
                results.append((
                    tuple(bullet_tags.known_terms(resume)),
                    tuple(sorted(bullet_tags.match_tags(b)) for b in resume.all_bullets()),
                    tuple(round(selection._keyword_score(b, reqs), 6) for b in resume.all_bullets()),
                ))
            return tuple(results)

    serial = {name: one_run(name) for name in runs}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(name, pool.submit(one_run, name)) for name in ["a", "b"] * 8]
        for name, future in futures:
            assert future.result(timeout=30) == serial[name]
