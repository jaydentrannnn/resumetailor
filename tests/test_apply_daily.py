"""Hermetic tests for the daily apply orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_tailor import config, jd
from resume_tailor.apply import browser, daily, fetch_jd, fill, sources, store
from resume_tailor.apply.sources import SourceRow
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.jobs import Job, JobQueue
from resume_tailor.web.schemas import ApplySettings, JobSettings


@pytest.fixture
def apply_paths(tmp_path, monkeypatch):
    """Isolate applications registry, output tree, and cache."""
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "output" / "jobs").mkdir(parents=True)
    return tmp_path


def _sample_row(**overrides) -> SourceRow:
    """Build one parsed README row for daily tests."""
    data_row = {
        "company": "Acme Corp",
        "role": "Software Intern",
        "location": "Remote",
        "age": "0d",
        "job_id": "aaa11111-1111-1111-1111-111111111111",
        "application_link": "https://boards.greenhouse.io/acme/jobs/1",
    }
    data_row.update(overrides)
    return SourceRow(**data_row)


def _write_prior_run(root: Path, job_id: str, *, company: str, jd_text: str) -> None:
    """Seed an archived run directory for reuse tests."""
    d = root / "output" / "jobs" / job_id
    d.mkdir(parents=True)
    (d / "jd.txt").write_text(jd_text, encoding="utf-8")
    reqs = JobRequirements(
        title="Intern",
        seniority="intern",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    (d / "requirements.json").write_text(reqs.model_dump_json(), encoding="utf-8")
    (d / "bullets.json").write_text(json.dumps({"a": "Built Python services."}), encoding="utf-8")
    (d / "run.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "status": "succeeded",
                "metadata": {"company": company, "role": "Intern"},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def stub_pipeline(monkeypatch, apply_paths):
    """Stub external IO and the tailor queue for deterministic daily runs."""
    from resume_tailor.apply.screen import ScreenResult
    from tests.fixtures import synthetic_resume

    row = _sample_row()

    monkeypatch.setattr(
        sources,
        "fetch_readme",
        lambda url: "readme",
    )
    monkeypatch.setattr(
        sources,
        "parse_readme",
        lambda text, categories: [row],
    )

    def _fake_filter(rows, **kwargs):
        """Honor ``known_ids`` so multi-source stubs still dedupe like production."""
        known = kwargs.get("known_ids") or set()
        sample = next(iter(known), None) if known else None
        if isinstance(sample, tuple):
            is_known = (row.source_id or "simplify", row.job_id) in known
        else:
            is_known = row.job_id in known
        if is_known:
            return sources.FilterResult(
                new_rows=[], total_candidates=1, already_known=1
            )
        return sources.FilterResult(new_rows=[row], total_candidates=1)

    monkeypatch.setattr(sources, "filter_rows", _fake_filter)

    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="We need Python and software engineering interns. " * 20,
            method="http",
        ),
    )

    requirements = JobRequirements(
        title="Software Intern",
        seniority="intern",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    monkeypatch.setattr(
        jd,
        "extract_consensus",
        lambda text, known_tags, **kwargs: requirements,
    )
    monkeypatch.setattr(daily.data, "load", lambda: synthetic_resume())
    monkeypatch.setattr(
        daily,
        "screen",
        lambda *a, **k: ScreenResult(
            passed=True,
            coverage=1.0,
            coverage_matched=1,
            coverage_total=1,
            seniority="intern",
        ),
    )

    queue = JobQueue()

    def _submit(jd_text, settings, metadata=None):
        job = Job(
            job_id="tailor-job-1",
            jd_text=jd_text,
            settings=settings,
            metadata=metadata,
            status="succeeded",
        )
        queue._jobs[job.job_id] = job
        return job, 1

    monkeypatch.setattr(queue, "submit", _submit)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: queue)
    monkeypatch.setattr(daily, "get_queue", lambda: queue)
    monkeypatch.setattr(
        daily,
        "_wait_for_job",
        lambda job_id, **kwargs: queue.get(job_id),
    )
    monkeypatch.setattr(
        daily.workspace,
        "load_settings",
        lambda workspace_id=None: {"defaults": JobSettings().model_dump()},
    )

    return row


def test_run_daily_progresses_new_posting(stub_pipeline, apply_paths):
    """One new row should reach ``ready`` after a successful tailor job."""
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert summary.already_running is False
    assert summary.new_rows == 1
    assert summary.processed == 1
    assert summary.ready == 1
    assert summary.tailored == 1

    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app is not None
    assert app.status == "ready"
    assert app.job_id == "tailor-job-1"


def test_run_daily_idempotent_on_known_ids(stub_pipeline, apply_paths, monkeypatch):
    """Second run with the same id in ``known_ids`` should not re-process."""
    daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    first = store.get("aaa11111-1111-1111-1111-111111111111")
    assert first is not None

    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=[], total_candidates=1, already_known=1
        ),
    )
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert summary.new_rows == 0
    assert summary.processed == 0


def test_run_daily_reuses_prior_run_when_company_matches(stub_pipeline, apply_paths, monkeypatch):
    """Reuse should skip the queue when jaccard recommends reuse and company matches."""
    jd_text = "python fastapi software engineering intern remote " * 5
    _write_prior_run(
        apply_paths,
        "prior-run",
        company="Acme Corp",
        jd_text=jd_text,
    )
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text=jd_text,
            method="http",
        ),
    )

    summary = daily.run_daily(
        settings=ApplySettings(enabled=True, max_new_per_day=5, reuse_threshold=0.72)
    )
    assert summary.reused == 1
    assert summary.ready == 1
    assert summary.tailored == 0

    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app.reused_from_job_id == "prior-run"
    assert app.job_id == "prior-run"


def test_run_daily_already_running_returns_early(apply_paths):
    """A concurrent call should report ``already_running`` without mutating state."""
    assert daily._DAILY_LOCK.acquire(blocking=False)  # noqa: SLF001 - lock contract test
    try:
        summary = daily.run_daily(settings=ApplySettings(enabled=True))
        assert summary.already_running is True
    finally:
        daily._DAILY_LOCK.release()


def test_run_daily_dry_run_discovers_without_tailoring(stub_pipeline, apply_paths, monkeypatch):
    """Dry run records discovery only — no JD fetch or queue submit."""
    fetch_calls: list[str] = []

    def _track_fetch(url, allow_browser=True, canonical_key=None):
        fetch_calls.append(url)
        return fetch_jd.FetchResult(final_url=url, ats="greenhouse", text="", method="failed")

    monkeypatch.setattr(fetch_jd, "fetch_jd", _track_fetch)
    summary = daily.run_daily(
        settings=ApplySettings(enabled=True, max_new_per_day=5),
        dry_run=True,
    )

    assert summary.discovered == 1
    assert summary.processed == 1
    assert fetch_calls == []
    assert store.get("aaa11111-1111-1111-1111-111111111111") is None


def test_run_daily_writes_log_file(stub_pipeline, apply_paths):
    """Daily run should append to ``log-YYYY-MM-DD.txt`` under applications output."""
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    log_path = Path(summary.log_path)
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "daily run" in text
    assert "[ready]" in text


def test_run_daily_logs_no_application_link(stub_pipeline, apply_paths, monkeypatch):
    """A discovered row with no posting link logs `[skipped]` instead of vanishing."""
    row = _sample_row(application_link="")
    monkeypatch.setattr(sources, "filter_rows", lambda rows, **kwargs: sources.FilterResult(
        new_rows=[row], total_candidates=1
    ))
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert summary.skipped_count == 1
    text = Path(summary.log_path).read_text(encoding="utf-8")
    assert "[skipped] Acme Corp: no application link" in text


def test_run_daily_logs_extract_failure(stub_pipeline, apply_paths, monkeypatch):
    """A raised `extract_consensus` exception logs `[tailor_failed]` instead of vanishing."""
    def _extract(text, known_tags, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(jd, "extract_consensus", _extract)
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert summary.tailor_failed == 1
    text = Path(summary.log_path).read_text(encoding="utf-8")
    assert "[tailor_failed] Acme Corp: extract failed: boom" in text


def test_run_daily_loops_multiple_simplify_sources(stub_pipeline, apply_paths, monkeypatch):
    """Enabled Simplify sources each contribute rows tagged with their ``source_id``."""
    from resume_tailor.web.schemas import SourceConfig

    intern_row = _sample_row(
        job_id="intern-id-0001",
        company="Intern Co",
        application_link="https://boards.greenhouse.io/intern/jobs/1",
    )
    newgrad_row = _sample_row(
        job_id="newgrad-id-0001",
        company="NewGrad Co",
        role="Software Engineer New Grad",
        application_link="https://boards.greenhouse.io/newgrad/jobs/2",
    )

    def _fetch(url: str) -> str:
        """Return distinct bodies so the parse stub can pick the right row."""
        if "New-Grad" in url:
            return "newgrad-readme"
        return "intern-readme"

    def _parse(text: str, categories: list[str]):
        """Return the row matching the stubbed README body."""
        if text == "newgrad-readme":
            return [newgrad_row]
        return [intern_row]

    monkeypatch.setattr(sources, "fetch_readme", _fetch)
    monkeypatch.setattr(sources, "parse_readme", _parse)
    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=list(rows), total_candidates=len(rows)
        ),
    )

    settings = ApplySettings(
        enabled=True,
        max_new_per_day=10,
        sources=[
            SourceConfig(
                id="simplify-internships",
                kind="simplify_html",
                url="https://example.com/Summer2027-Internships/README.md",
                categories=["Software Engineering Internship Roles"],
            ),
            SourceConfig(
                id="simplify-newgrad",
                kind="simplify_html",
                url="https://example.com/New-Grad-Positions/README.md",
                categories=["Software Engineering New Grad Roles"],
            ),
        ],
    )
    summary = daily.run_daily(settings=settings, dry_run=True)
    assert summary.new_rows == 2
    assert summary.discovered == 2
    log = Path(summary.log_path).read_text(encoding="utf-8")
    assert "[source simplify-internships]" in log
    assert "[source simplify-newgrad]" in log


def test_canonical_dedupe_merges_source_refs(stub_pipeline, apply_paths, monkeypatch):
    """Simplify wrapper + direct ATS URL for the same requisition share one record."""
    from resume_tailor.apply import identity
    from resume_tailor.web.schemas import SourceConfig

    figma = "https://boards.greenhouse.io/figma/jobs/6143238004"
    row_a = _sample_row(
        job_id="simp-uuid-1",
        company="Figma",
        application_link="https://simplify.jobs/p/simp-uuid-1",
        source_id="simplify-internships",
    )
    row_b = _sample_row(
        job_id="speedy-hash-1",
        company="Figma",
        application_link=figma,
        source_id="speedyapply",
    )

    monkeypatch.setattr(
        identity,
        "resolve_final_url",
        lambda url, **kwargs: figma,
    )
    monkeypatch.setattr(sources, "fetch_readme", lambda url: "x")
    monkeypatch.setattr(
        sources,
        "parse_readme",
        lambda text, categories: [row_a],
    )
    monkeypatch.setattr(
        sources,
        "parse_pipe_table_readme",
        lambda text, categories: [row_b],
    )
    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=list(rows), total_candidates=len(rows)
        ),
    )

    settings = ApplySettings(
        enabled=True,
        max_new_per_day=10,
        sources=[
            SourceConfig(
                id="simplify-internships",
                kind="simplify_html",
                url="https://example.com/a",
                categories=["X"],
            ),
            SourceConfig(
                id="speedyapply",
                kind="pipe_table",
                url="https://example.com/b",
                categories=["Y"],
            ),
        ],
    )
    summary = daily.run_daily(settings=settings)
    assert summary.already_known >= 1 or summary.discovered == 1
    apps = store.load_all()
    assert len(apps) == 1
    app = next(iter(apps.values()))
    assert app.canonical_key == "greenhouse:figma:6143238004"
    sources_seen = {ref.source for ref in app.source_refs}
    assert "simplify-internships" in sources_seen
    assert "speedyapply" in sources_seen


def test_group_key_reuses_tailoring(stub_pipeline, apply_paths, monkeypatch):
    """Same company+role across locations reuses the primary's job_id."""
    from resume_tailor.apply import identity
    from resume_tailor.web.schemas import SourceConfig

    baltimore = _sample_row(
        job_id="northrop-balt",
        company="Northrop Grumman",
        role="2027 Embedded Software Engineer Intern - Baltimore MD",
        application_link="https://boards.greenhouse.io/northrop/jobs/1",
    )
    camarillo = _sample_row(
        job_id="northrop-cam",
        company="Northrop Grumman",
        role="2027 Embedded Software Engineer Intern - Camarillo CA",
        application_link="https://boards.greenhouse.io/northrop/jobs/2",
    )
    # Seed primary as ready with a tailor job_id.
    primary = store.Application(
        source="simplify-internships",
        source_job_id="northrop-balt",
        company="Northrop Grumman",
        role=baltimore.role,
        posting_url=baltimore.application_link or "",
        canonical_key="greenhouse:northrop:1",
        group_key=identity.group_key(baltimore.company, baltimore.role),
        job_id="tailor-job-1",
        status="ready",
        source_refs=[
            store.SourceRef(
                source="simplify-internships",
                source_job_id="northrop-balt",
                url=baltimore.application_link or "",
            )
        ],
    )
    store.upsert(primary)

    monkeypatch.setattr(identity, "resolve_final_url", lambda url, **k: url)
    monkeypatch.setattr(sources, "fetch_readme", lambda url: "x")
    monkeypatch.setattr(sources, "parse_readme", lambda text, categories: [camarillo])
    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=list(rows), total_candidates=len(rows)
        ),
    )

    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        sources=[
            SourceConfig(
                id="simplify-internships",
                kind="simplify_html",
                url="https://example.com/a",
                categories=["X"],
            )
        ],
    )
    summary = daily.run_daily(settings=settings)
    assert summary.grouped == 1
    dup = store.get("northrop-cam")
    assert dup is not None
    assert dup.duplicate_of == "greenhouse:northrop:1"
    assert dup.reused_from_job_id == "tailor-job-1"
    assert dup.status == "ready"


def test_prefilter_skips_extract_consensus(stub_pipeline, apply_paths, monkeypatch):
    """A JD with ``PhD required`` is screened out before extract_consensus."""
    calls: list[str] = []

    def _extract(text, known_tags, **kwargs):
        calls.append(text)
        raise AssertionError("extract should not run")

    monkeypatch.setattr(jd, "extract_consensus", _extract)
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="PhD required. " + ("research experience in ML. " * 30),
            method="http",
        ),
    )
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert calls == []
    assert summary.prefiltered_out == 1
    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app is not None
    assert app.status == "screened_out"
    assert app.status_history[-1].note.startswith("prefilter:")


def test_extract_consensus_pinned_to_apply_settings_model(apply_paths, monkeypatch):
    """`_process_one` pins `config` to `ApplySettings.model_spec` before extracting.

    Regression guard for the bug found 2026-09-21: with `_ACTIVE` empty (a fresh
    process), `jd.extract_consensus` used to silently fall through to
    `config.backend_for`'s hardcoded Claude default, ignoring the workspace's model
    setting entirely.
    """
    row = _sample_row()
    monkeypatch.setattr(sources, "fetch_readme", lambda url: "x")
    monkeypatch.setattr(sources, "parse_readme", lambda text, categories: [row])
    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=list(rows), total_candidates=1
        ),
    )
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="Python software engineering intern. " * 20,
            method="http",
        ),
    )
    seen: dict[str, str] = {}

    def _extract(text, known_tags, **kwargs):
        backend = config.backend_for("extract")
        seen["origin"] = backend.origin
        seen["model"] = backend.model
        raise RuntimeError("stop before tailoring — only checking the pin")

    monkeypatch.setattr(jd, "extract_consensus", _extract)

    # Confirm the exposure directly: with `_ACTIVE` empty, a real bug would resolve
    # to Claude here.
    config._ACTIVE.clear()
    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        model_provider="lmstudio",
        model_name="some-test-model",
    )
    summary = daily.run_daily(settings=settings)
    assert seen == {"origin": "lmstudio", "model": "some-test-model"}
    assert summary.tailor_failed == 1
    assert "stop before tailoring" in summary.errors[0]


def test_try_start_daily_passes_limit_and_dry_run(monkeypatch, apply_paths):
    """The API-started thread receives the limit and dry_run from the caller."""
    called_with: dict[str, Any] = {}

    def _fake_run(**kwargs):
        called_with.update(kwargs)
        return daily.DailySummary()

    monkeypatch.setattr(daily, "run_daily", _fake_run)
    daily.try_start_daily(limit=3, dry_run=True)
    # Give the daemon thread a moment to start.
    import time

    deadline = time.monotonic() + 2.0
    while not called_with and time.monotonic() < deadline:
        time.sleep(0.05)
    assert called_with.get("limit") == 3
    assert called_with.get("dry_run") is True


def test_daily_status_reflects_progress(apply_paths, monkeypatch):
    """`daily_status()` reports phase/counters while a run is in flight."""
    from resume_tailor.web.schemas import SourceConfig

    # Fast-path: a single row, no network.
    row = _sample_row()
    monkeypatch.setattr(sources, "fetch_readme", lambda url: "x")
    monkeypatch.setattr(sources, "parse_readme", lambda text, categories: [row])
    monkeypatch.setattr(
        sources,
        "filter_rows",
        lambda rows, **kwargs: sources.FilterResult(
            new_rows=list(rows), total_candidates=1
        ),
    )
    def _slow_fetch(url, allow_browser=True, canonical_key=None):
        """A tiny delay so the poll loop below reliably observes an in-flight phase —
        a real fetch always takes some wall-clock time; a truly instant stub can finish
        the whole run between two 0.1s polls."""
        import time as _time

        _time.sleep(0.2)
        return fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="We need Python interns. " * 20,
            method="http",
        )

    monkeypatch.setattr(fetch_jd, "fetch_jd", _slow_fetch)
    requirements = JobRequirements(
        title="Software Intern",
        seniority="intern",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )
    monkeypatch.setattr(
        jd, "extract_consensus", lambda text, known_tags, **kwargs: requirements
    )
    from tests.fixtures import synthetic_resume
    from resume_tailor.apply.screen import ScreenResult

    monkeypatch.setattr(daily.data, "load", lambda: synthetic_resume())
    monkeypatch.setattr(
        daily,
        "screen",
        lambda *a, **k: ScreenResult(
            passed=True,
            coverage=1.0,
            coverage_matched=1,
            coverage_total=1,
            seniority="intern",
        ),
    )
    _queue = JobQueue()

    def _submit(jd_text, run_settings, metadata=None):
        job = Job(
            job_id="tailor-job-1",
            jd_text=jd_text,
            settings=run_settings,
            metadata=metadata,
            status="succeeded",
        )
        _queue._jobs[job.job_id] = job
        return job, 1

    monkeypatch.setattr(_queue, "submit", _submit)
    monkeypatch.setattr(jobs_mod, "get_queue", lambda: _queue)
    monkeypatch.setattr(daily, "get_queue", lambda: _queue)
    monkeypatch.setattr(daily, "_wait_for_job", lambda job_id, **kwargs: _queue.get(job_id))
    monkeypatch.setattr(
        daily.workspace,
        "load_settings",
        lambda workspace_id=None: {"defaults": JobSettings().model_dump()},
    )

    settings = ApplySettings(
        enabled=True,
        max_new_per_day=1,
        sources=[
            SourceConfig(
                id="simplify-internships",
                kind="simplify_html",
                url="https://example.com/a",
                categories=["X"],
            )
        ],
    )
    # Run on a thread so we can poll daily_status() mid-flight.
    import time, threading

    def _runner():
        daily.run_daily(settings=settings, limit=1)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    # Poll until the run finishes.
    deadline = time.monotonic() + 10.0
    seen_discovering = False
    while daily.daily_busy() and time.monotonic() < deadline:
        status = daily.daily_status()
        assert status.running is True
        if status.phase in {"discovering", "processing"}:
            seen_discovering = True
        time.sleep(0.1)
    t.join(timeout=2.0)

    assert seen_discovering, "daily_status never left the idle phase"
    final = daily.daily_status()
    assert final.running is False
    assert final.phase == "done"
    assert final.summary is not None
    assert final.summary.processed == 1


def _ready_app(source_job_id: str, *, ats: str, discovered_at: str) -> store.Application:
    """Build one `ready`, tailored application for batch-submit tests."""
    return store.Application(
        source="simplify-internships",
        source_job_id=source_job_id,
        company="Acme Corp",
        role="Software Intern",
        ats=ats,
        status="ready",
        job_id="tailor-job-1",
        canonical_key=f"{ats}:acme:{source_job_id}",
        discovered_at=discovered_at,
    )


def test_run_batch_submit_noop_when_cap_zero(apply_paths, monkeypatch):
    """cap=0 (the default) must not touch any application or call fill."""
    app = _ready_app("a1", ats="greenhouse", discovered_at="2026-01-01T00:00:00+00:00")
    store.upsert(app)
    monkeypatch.setattr(
        fill, "fill_application", lambda *a, **k: pytest.fail("must not be called")
    )

    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=0,
        dry_run=False,
        log_path=apply_paths / "log.txt",
        log=lambda *_: None,
        summary=summary,
    )

    assert summary.submit_attempted == 0
    assert store.get("a1").status == "ready"


def test_run_batch_submit_respects_cap_oldest_first(apply_paths, monkeypatch):
    """Only the cap's worth of eligible ready apps are submitted, oldest discovered first."""
    for i, ts in enumerate(
        ["2026-01-03T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"]
    ):
        store.upsert(_ready_app(f"a{i}", ats="greenhouse", discovered_at=ts))

    calls: list[str] = []

    def _fake_fill(key, **kwargs):
        calls.append(key)
        return store.FillResult(status="submitted")

    monkeypatch.setattr(fill, "fill_application", _fake_fill)
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))

    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=2,
        dry_run=False,
        log_path=apply_paths / "log.txt",
        log=lambda *_: None,
        summary=summary,
    )

    # a1 (Jan 1) then a2 (Jan 2) — a0 (Jan 3) is left for the next run.
    assert calls == ["greenhouse:acme:a1", "greenhouse:acme:a2"]
    assert summary.submit_attempted == 2
    assert summary.submitted == 2


def test_run_batch_submit_skips_non_eligible_ats(apply_paths, monkeypatch):
    """A ready app whose ATS isn't in auto_submit_ats is left untouched."""
    store.upsert(_ready_app("a1", ats="lever", discovered_at="2026-01-01T00:00:00+00:00"))
    monkeypatch.setattr(
        fill, "fill_application", lambda *a, **k: pytest.fail("must not be called")
    )
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))

    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=5,
        dry_run=False,
        log_path=apply_paths / "log.txt",
        log=lambda *_: None,
        summary=summary,
    )

    assert summary.submit_attempted == 0
    assert store.get("a1").status == "ready"


def test_run_batch_submit_skips_when_browser_unreachable(apply_paths, monkeypatch):
    """An unreachable Chrome CDP endpoint skips the whole stage, not a mass fill_failed."""
    store.upsert(_ready_app("a1", ats="greenhouse", discovered_at="2026-01-01T00:00:00+00:00"))
    monkeypatch.setattr(
        fill, "fill_application", lambda *a, **k: pytest.fail("must not be called")
    )
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=False))

    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=5,
        dry_run=False,
        log_path=apply_paths / "log.txt",
        log=lambda *_: None,
        summary=summary,
    )

    assert summary.submit_skipped_no_browser is True
    assert summary.submit_attempted == 0
    assert store.get("a1").status == "ready"


def test_run_batch_submit_dry_run_logs_without_calling_fill(apply_paths, monkeypatch):
    """dry_run only logs the would-be submissions; no real fill call, no status change."""
    store.upsert(_ready_app("a1", ats="greenhouse", discovered_at="2026-01-01T00:00:00+00:00"))
    monkeypatch.setattr(
        fill, "fill_application", lambda *a, **k: pytest.fail("must not be called")
    )
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))

    logged: list[str] = []
    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=5,
        dry_run=True,
        log_path=apply_paths / "log.txt",
        log=logged.append,
        summary=summary,
    )

    assert summary.submit_attempted == 0
    assert any("would-submit" in line for line in logged)
    assert store.get("a1").status == "ready"


def test_run_batch_submit_one_failure_does_not_sink_the_batch(apply_paths, monkeypatch):
    """A per-item fill exception is recorded and the batch continues to the next item."""
    store.upsert(_ready_app("a1", ats="greenhouse", discovered_at="2026-01-01T00:00:00+00:00"))
    store.upsert(_ready_app("a2", ats="greenhouse", discovered_at="2026-01-02T00:00:00+00:00"))

    def _fake_fill(key, **kwargs):
        if key.endswith("a1"):
            raise RuntimeError("boom")
        return store.FillResult(status="submitted")

    monkeypatch.setattr(fill, "fill_application", _fake_fill)
    monkeypatch.setattr(browser, "browser_status", lambda: browser.BrowserStatus(reachable=True))

    summary = daily.DailySummary()
    daily._run_batch_submit(
        settings=ApplySettings(auto_submit_ats=["greenhouse"]),
        cap=5,
        dry_run=False,
        log_path=apply_paths / "log.txt",
        log=lambda *_: None,
        summary=summary,
    )

    assert summary.submit_attempted == 2
    assert summary.submitted == 1
    assert summary.submit_failed == 1


def test_try_start_daily_passes_max_submissions(monkeypatch, apply_paths):
    """The API-started thread receives the auto_submit_max_per_run override."""
    called_with: dict[str, Any] = {}

    def _fake_run(**kwargs):
        called_with.update(kwargs)
        return daily.DailySummary()

    monkeypatch.setattr(daily, "run_daily", _fake_run)
    daily.try_start_daily(max_submissions=5)
    import time

    deadline = time.monotonic() + 2.0
    while not called_with and time.monotonic() < deadline:
        time.sleep(0.05)
    assert called_with.get("auto_submit_max_per_run") == 5