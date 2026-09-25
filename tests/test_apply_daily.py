"""Hermetic tests for the daily apply orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from resume_tailor import config, jd
from resume_tailor.apply import browser, daily, fetch_jd, fill, sources, store
from resume_tailor.apply.sources import SourceRow
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.jobs import Job, JobQueue
from resume_tailor.web.schemas import ApplySettings, JobSettings


def test_apply_job_settings_keeps_tailor_model_routing():
    """Apply-launched tailoring uses the Tailor tab's routing, never the autofill model.

    Regression: `_job_settings` used to overwrite every model field with
    `ApplySettings.model_spec` (then `nemotron-3-super:cloud`), so Prepare ran a slow
    reasoning model while the Tailor tab ran `gemma4:cloud` for the same resume.
    """
    base = JobSettings(
        model="ollama",
        model_name="gemma4:cloud",
        effort="low",
        rewrite_model="rewrite-model",
        cover_letter=False,
    )
    merged = daily._job_settings(
        base,
        ApplySettings(model_provider="lmstudio", model_name="autofill-model", cover_letter=True),
    )
    assert merged.model == "ollama"
    assert merged.model_name == "gemma4:cloud"
    assert merged.effort == "low"
    assert merged.rewrite_model == "rewrite-model"
    assert merged.cover_letter is True
    assert base.cover_letter is False  # the workspace defaults object is not mutated


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
    assert app.archived_at == app.status_history[-1].at
    assert app.status_history[-1].note.startswith("prefilter:")


def test_work_restriction_is_screened_before_extract_consensus(
    stub_pipeline, apply_paths, monkeypatch
):
    """A citizenship-only posting is screened out by the free text check, never
    reaching the LLM extraction."""

    def _extract(text, known_tags, **kwargs):
        raise AssertionError("extract should not run")

    monkeypatch.setattr(jd, "extract_consensus", _extract)
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="Software intern building satellites. " * 10
            + "Applicant must be a U.S. citizen or lawful permanent resident.",
            method="http",
        ),
    )
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    assert summary.prefiltered_out == 1
    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app is not None and app.screen is not None
    assert app.status == "screened_out"
    assert app.archived_at == app.status_history[-1].at
    assert app.screen.reasons == ["citizenship_required"]
    assert "U.S. citizen" in app.screen.evidence[0]


def test_resume_screen_rejection_is_archived(stub_pipeline, apply_paths, monkeypatch):
    from resume_tailor.apply.screen import ScreenResult

    monkeypatch.setattr(
        daily,
        "screen",
        lambda *args, **kwargs: ScreenResult(passed=False, reasons=["seniority_mismatch"]),
    )
    summary = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5))
    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert summary.screened_out == 1
    assert app is not None and app.status == "screened_out"
    assert app.archived_at == app.status_history[-1].at
    assert app.screen is not None and app.screen.reasons == ["seniority_mismatch"]


def test_extract_consensus_pinned_to_tailor_routing(apply_paths, monkeypatch):
    """`_process_one` pins `config` to the Tailor tab's routing before extracting.

    Regression guards: (2026-09-21) with `_ACTIVE` empty (a fresh process),
    `jd.extract_consensus` used to fall through to `config.backend_for`'s hardcoded
    Claude default; (2026-09-23) it then ran on the Apply autofill model with a single
    vote, so the tailor job — on different routing, asking for `extract_runs` votes —
    cache-missed and re-read the JD `extract_runs` more times.
    """
    from tests.fixtures import synthetic_resume

    resume_path = apply_paths / "master_resume.json"
    resume_path.write_text(synthetic_resume().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", resume_path)
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
    seen: dict[str, object] = {}

    def _extract(text, known_tags, **kwargs):
        backend = config.backend_for("extract")
        seen["origin"] = backend.origin
        seen["model"] = backend.model
        seen["runs"] = kwargs.get("runs")
        raise RuntimeError("stop before tailoring — only checking the pin")

    monkeypatch.setattr(jd, "extract_consensus", _extract)

    # Confirm the exposure directly: with `_ACTIVE` empty, a real bug would resolve
    # to Claude here.
    config._ACTIVE.clear()
    tailor = JobSettings(model="lmstudio", model_name="tailor-model", extract_runs=3)
    monkeypatch.setattr(
        daily.workspace, "load_settings", lambda: {"defaults": tailor.model_dump()}
    )
    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        model_provider="ollama",
        model_name="autofill-model",
    )
    summary = daily.run_daily(settings=settings)
    assert seen == {"origin": "lmstudio", "model": "tailor-model", "runs": 3}
    assert summary.tailor_failed == 1
    assert "stop before tailoring" in summary.errors[0]


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
    from resume_tailor.apply.screen import ScreenResult
    from tests.fixtures import synthetic_resume

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
    import threading
    import time

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


def test_run_daily_fetch_only(stub_pipeline, apply_paths):
    """fetch_only=True ingests applications as 'discovered' without JD fetch or tailoring."""
    summary = daily.run_daily(
        settings=ApplySettings(enabled=True, max_new_per_day=5),
        fetch_only=True,
    )
    assert summary.already_running is False
    assert summary.new_rows == 1
    assert summary.discovered == 1
    assert summary.processed == 1
    assert summary.ready == 0
    assert summary.tailored == 0
    assert summary.jd_fetched == 0

    app = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app is not None
    assert app.status == "discovered"
    assert app.job_id is None

    # A subsequent normal daily run should pick up the pending discovered app and progress it to ready
    summary2 = daily.run_daily(
        settings=ApplySettings(enabled=True, max_new_per_day=5),
        fetch_only=False,
    )
    assert summary2.already_running is False
    assert summary2.ready == 1
    assert summary2.tailored == 1
    app_ready = store.get("aaa11111-1111-1111-1111-111111111111")
    assert app_ready is not None
    assert app_ready.status == "ready"
    assert app_ready.job_id == "tailor-job-1"


def test_archived_discovery_is_not_prepared_by_daily_run(stub_pipeline, apply_paths):
    daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5), fetch_only=True)
    application_id = "aaa11111-1111-1111-1111-111111111111"
    store.set_archived([application_id], True)
    result = daily.run_daily(settings=ApplySettings(enabled=True, max_new_per_day=5), fetch_only=False)
    archived = store.get(application_id)
    assert result.ready == 0
    assert archived is not None and archived.archived_at
    assert archived.status == "discovered"
    with pytest.raises(RuntimeError, match="archived"):
        daily.prepare_application(application_id, settings=ApplySettings(enabled=True))

def _retry_app(status: str, *, note: str = "", **overrides: Any) -> store.Application:
    """One application at ``status`` whose last history note is ``note``."""
    app = store.Application(
        **{
            "source": "simplify-internships",
            "source_job_id": "retry-1",
            "company": "Acme Corp",
            "role": "Software Intern",
            "status": status,
            "posting_url": "https://example.com/job",
            **overrides,
        }
    )
    if note:
        app.status_history.append(store.StatusChange(status=status, at="2026-09-23T00:00:00+00:00", note=note))
    return app


@pytest.mark.parametrize(
    ("status", "note", "expected"),
    [
        ("discovered", "", "fetch"),
        ("needs_browser", "", "fetch"),
        ("jd_fetched", "", "fetch"),
        ("screened_out", "prefilter: 5+ years required", None),
        ("screened_out", "screen: seniority mismatch", None),
        ("tailor_failed", "", "tailor"),
        ("ready", "", None),
        ("skipped", "", None),
    ],
)
def test_retry_kind_matches_retry_application_branches(status, note, expected):
    """`retry_kind` is the single definition of what the Retry button can do."""
    assert daily.retry_kind(_retry_app(status, note=note)) == expected


@pytest.mark.parametrize("note", ["prefilter: requires_5_years", "seniority 'mid' not in ['intern', 'entry']"])
def test_any_screen_out_with_saved_jd_can_be_rechecked(note):
    """Both prefilter and screen-stage rejections re-check without a model call."""
    app = _retry_app("screened_out", note=note, jd_text_path="jd.txt")
    assert daily.retry_kind(app) == "prefilter"


def test_retry_application_refuses_screened_out_without_saved_jd(apply_paths):
    """With no saved JD text there is nothing to re-check, so the API must not offer it."""
    store.upsert(_retry_app("screened_out", note="screen: seniority mismatch"))
    with pytest.raises(RuntimeError, match="no retry path"):
        daily.retry_application("retry-1")


def _recheck_settings(monkeypatch):
    monkeypatch.setattr(
        daily.workspace,
        "load_settings",
        lambda workspace_id=None: {"defaults": JobSettings().model_dump()},
    )


def test_recheck_clears_a_stale_screen_out(apply_paths, monkeypatch):
    """A row rejected by an old rule (30-year misparse, model seniority on an intern
    title) clears under the current rules and returns to `jd_fetched`."""
    from resume_tailor.apply.screen import ScreenResult

    _recheck_settings(monkeypatch)
    jd_path = apply_paths / "jd.txt"
    jd_path.write_text(
        "For over 30 years we have built games. Analytics intern, Python and SQL.",
        encoding="utf-8",
    )
    store.upsert(
        _retry_app(
            "screened_out",
            note="seniority 'mid' not in ['intern', 'entry']",
            role="Analytics Intern",
            jd_text_path=str(jd_path),
            screen=ScreenResult(passed=False, reasons=["requires_30_years"], seniority="mid"),
        )
    )
    after = daily.retry_application("retry-1")
    assert after.status == "jd_fetched"
    assert after.status_history[-1].note == "eligibility cleared on re-check"
    assert "seniority_mismatch" in after.eligibility_flags


def test_recheck_keeps_a_real_restriction_with_its_evidence(apply_paths, monkeypatch):
    _recheck_settings(monkeypatch)
    jd_path = apply_paths / "jd.txt"
    jd_path.write_text(
        "Build radar software. U.S. citizenship is required, as only U.S. citizens "
        "are eligible for a security clearance. Python preferred.",
        encoding="utf-8",
    )
    store.upsert(_retry_app("screened_out", jd_text_path=str(jd_path)))
    after = daily.retry_application("retry-1")
    assert after.status == "screened_out"
    assert after.archived_at == after.status_history[-1].at
    assert after.screen is not None
    assert after.screen.reasons == ["citizenship_required", "clearance_required"]
    assert after.screen.evidence[0].startswith("U.S. citizenship is required")


def test_tailor_retry_returns_before_the_job_finishes(apply_paths, monkeypatch):
    """A tailor retry queues the job and returns at `tailoring`; a thread records the result."""
    import threading

    jd_path = apply_paths / "jd.txt"
    jd_path.write_text("Software intern. Python.", encoding="utf-8")
    store.upsert(_retry_app("tailor_failed", jd_text_path=str(jd_path)))

    class _Queue:
        def submit(self, jd_text, settings, metadata=None):
            return Job(job_id="retry-job", jd_text=jd_text, settings=settings), 0

    release = threading.Event()

    class _Finished:
        status = "succeeded"
        error = None

    def fake_wait(job_id, *, timeout_sec=3600.0, poll_sec=0.5):
        assert job_id == "retry-job"
        release.wait(timeout=5)
        return _Finished()

    monkeypatch.setattr(daily, "get_queue", lambda: _Queue())
    monkeypatch.setattr(daily, "_wait_for_job", fake_wait)
    monkeypatch.setattr(daily.workspace, "load_settings", lambda: {"defaults": JobSettings().model_dump()})

    returned = daily.retry_application("retry-1")
    assert returned.status == "tailoring"
    assert returned.job_id == "retry-job"

    release.set()
    for thread in threading.enumerate():
        if thread.name == "apply-retry-retry-1":
            thread.join(timeout=5)
    assert store.get("retry-1").status == "ready"


def test_application_from_row_sets_ats_from_url():
    """A discovered row records its ATS immediately, not just after its first fetch
    (fixes the Applications page showing "unknown" for every just-discovered
    Workday row)."""
    row = _sample_row(
        application_link=(
            "https://amfam.wd1.myworkdayjobs.com/AmFamGroupInternCareers/job/"
            "WI-Madison/Consumer-Research-and-Insights-Intern-2027_R39474"
        )
    )
    app = daily._application_from_row(
        row,
        canonical_key="workday:amfam:r39474",
        group_key="amfam|intern",
        final_url=row.application_link,
    )
    assert app.ats == "workday"


def test_retry_application_fetch_rejects_short_text(apply_paths, monkeypatch):
    """A fetch retry that returns under the shared minimum length stays
    ``needs_browser``, matching what the nightly run would have done — it must
    not slip a scrap of text past the same rule under a different name."""
    store.upsert(_retry_app("needs_browser"))
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url, ats="workday", text="too short", method="api"
        ),
    )
    returned = daily.retry_application("retry-1")
    assert returned.status == "needs_browser"


def test_prepare_application_clears_stale_error_on_fetch_success(
    stub_pipeline, apply_paths
):
    """A row stuck at ``needs_browser`` with a leftover ``error`` from a prior failed
    fetch attempt (nightly run or a per-row retry) must not keep showing that error
    once "Prepare selected" fetches it successfully — regression for a bug where
    `_process_one`'s fetch-success path never touched `app.error`, so the Applications
    page kept showing "Browser extraction too short (0 chars)" on a row that had
    already moved past `jd_fetched` into `tailoring`/`ready`."""
    row = _sample_row()
    stale = store.Application(
        source="simplify",
        source_job_id=row.job_id,
        company=row.company,
        role=row.role,
        posting_url=row.application_link,
        final_url=row.application_link,
        canonical_key=f"pending:{row.job_id}",
        status="needs_browser",
        error="Browser extraction too short (0 chars)",
    )
    store.upsert(stale)

    prepared = daily.prepare_application(
        row.job_id, settings=ApplySettings(enabled=True)
    )
    assert prepared.status == "ready"
    assert prepared.error is None


def test_wait_for_job_relays_progress_events(monkeypatch):
    """`_wait_for_job`'s ``on_progress`` sees each new tailor-stage message once,
    in order, and stops seeing updates once the job is terminal — the Apply funnel's
    only visibility into what a long single tailor call is doing while it waits."""
    from resume_tailor.events import ProgressEvent

    job = Job(job_id="job-1", jd_text="jd", settings=JobSettings(), status="queued")
    queue = JobQueue()
    queue._jobs[job.job_id] = job
    monkeypatch.setattr(daily, "get_queue", lambda: queue)

    ticks = iter(
        [
            None,  # queued, no events yet
            ProgressEvent(stage="extract", message="Extracting job requirements"),
            ProgressEvent(stage="extract", message="Extracting job requirements"),  # repeat
            ProgressEvent(stage="rewrite", message="Rewriting bullets"),
        ]
    )
    seen: list[str] = []

    def _tick(*_a, **_k):
        event = next(ticks, "done")
        if event == "done":
            job.status = "succeeded"
        elif event is not None:
            job.events.append(event)

    monkeypatch.setattr(daily.time, "sleep", _tick)
    result = daily._wait_for_job(job.job_id, on_progress=seen.append)
    assert result is job
    assert result.status == "succeeded"
    assert seen == ["Extracting job requirements", "Rewriting bullets"]


def test_failed_prepare_again_does_not_restore_orphaned_tailoring(
    stub_pipeline, apply_paths, monkeypatch
):
    """A row left at ``tailoring`` by a job that died with a server restart must show
    the new attempt's outcome when Prepare fails — restoring ``previous`` once
    resurrected the dead ``tailoring`` row (and its stale error) forever."""
    row = _sample_row()
    store.upsert(
        store.Application(
            source="simplify",
            source_job_id=row.job_id,
            company=row.company,
            role="Software Engineer",
            posting_url=row.application_link,
            final_url=row.application_link,
            canonical_key=f"pending:{row.job_id}",
            status="tailoring",
            job_id="dead-job",
            error="Browser extraction too short (0 chars)",
        )
    )
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="Requires 5+ years of professional experience. " * 20,
            method="http",
        ),
    )

    with pytest.raises(RuntimeError, match="screened_out"):
        daily.prepare_application(row.job_id, settings=ApplySettings(enabled=True))

    after = store.get(row.job_id)
    assert after is not None
    assert after.status == "screened_out"
    assert after.error is None
    assert after.screen is not None and "requires_5_years" in after.screen.reasons


def test_failed_prepare_again_restores_ready_packet(stub_pipeline, apply_paths, monkeypatch):
    """A refresh of a row that already had a packet keeps the packet on failure."""
    row = _sample_row()
    store.upsert(
        store.Application(
            source="simplify",
            source_job_id=row.job_id,
            company=row.company,
            role="Software Engineer",
            posting_url=row.application_link,
            final_url=row.application_link,
            canonical_key=f"pending:{row.job_id}",
            status="ready",
            job_id="old-job",
        )
    )
    monkeypatch.setattr(
        fetch_jd,
        "fetch_jd",
        lambda url, allow_browser=True, canonical_key=None: fetch_jd.FetchResult(
            final_url=url,
            ats="greenhouse",
            text="Requires 5+ years of professional experience. " * 20,
            method="http",
        ),
    )

    with pytest.raises(RuntimeError):
        daily.prepare_application(
            row.job_id, settings=ApplySettings(enabled=True), force_prepare=True
        )

    after = store.get(row.job_id)
    assert after is not None
    assert after.status == "ready"
    assert after.job_id == "old-job"


def test_recover_orphaned_tailoring_marks_only_dead_jobs(apply_paths, monkeypatch):
    queue = JobQueue()
    live = Job(job_id="live-job", jd_text="jd", settings=JobSettings(), status="running")
    queue._jobs[live.job_id] = live
    monkeypatch.setattr(daily, "get_queue", lambda: queue)

    def _app(source_job_id: str, status: str, job_id: str | None) -> store.Application:
        return store.Application(
            source="simplify",
            source_job_id=source_job_id,
            company="Acme Corp",
            role="Software Intern",
            canonical_key=f"pending:{source_job_id}",
            status=status,
            job_id=job_id,
        )

    store.upsert(_app("dead", "tailoring", "dead-job"))
    store.upsert(_app("nojob", "tailoring", None))
    store.upsert(_app("live", "tailoring", "live-job"))
    store.upsert(_app("done", "ready", "dead-job"))

    assert daily.recover_orphaned_tailoring() == 2

    statuses = {sid: store.get(sid).status for sid in ("dead", "nojob", "live", "done")}
    assert statuses == {
        "dead": "tailor_failed",
        "nojob": "tailor_failed",
        "live": "tailoring",
        "done": "ready",
    }
    assert "server restart" in (store.get("dead").error or "")
    assert daily.retry_kind(store.get("dead")) == "tailor"


@pytest.mark.parametrize(
    ("previous_status", "expected"),
    [("awaiting_review", "awaiting_review"), ("awaiting_otp", "awaiting_otp"), ("fill_failed", "ready")],
)
def test_prepare_again_keeps_only_a_live_review_tab(
    stub_pipeline, apply_paths, previous_status, expected
):
    """An open review tab survives a refresh; an old fill failure does not outlive its packet."""
    row = _sample_row()
    store.upsert(
        store.Application(
            source="simplify",
            source_job_id=row.job_id,
            company=row.company,
            role=row.role,
            posting_url=row.application_link,
            final_url=row.application_link,
            canonical_key=f"pending:{row.job_id}",
            status=previous_status,
            job_id="old-job",
            fill=store.FillResult(status=previous_status, handoff_reason="old attempt"),
        )
    )

    prepared = daily.prepare_application(
        row.job_id, settings=ApplySettings(enabled=True), force_prepare=True
    )

    assert prepared.status == expected
    assert prepared.fill is not None  # the last attempt's report stays for reference


def test_run_daily_reads_a_company_watchlist(apply_paths, monkeypatch):
    """An ``ats_board`` source lists its boards, keeps its own age limit, and reports a
    wrong board name without losing the others."""
    from datetime import UTC, datetime, timedelta

    from resume_tailor.apply import boards
    from tests.fixtures import synthetic_resume

    monkeypatch.setattr(daily.data, "load", synthetic_resume)
    monkeypatch.setattr(boards, "_sleep", lambda _s: None)
    fresh = (datetime.now(UTC) - timedelta(days=5)).isoformat()

    def fake_list(ats, slug):
        if slug == "gone":
            raise boards.BoardNotFound(slug)
        return [
            boards.BoardJob("7", "Summer Analyst", "New York, NY",
                            "https://boards.greenhouse.io/acme/jobs/7", fresh),
            boards.BoardJob("8", "Senior Associate", "New York, NY",
                            "https://boards.greenhouse.io/acme/jobs/8", fresh),
        ]

    monkeypatch.setattr(boards, "list_board", fake_list)
    settings = ApplySettings(
        enabled=True,
        max_new_per_day=5,
        max_age_days=1,  # the README limit; the watchlist keeps its own 7 days
        sources=[{
            "id": "watch", "kind": "ats_board",
            "boards": [{"ats": "greenhouse", "slug": "gone"},
                       {"ats": "greenhouse", "slug": "acme", "company": "Acme"}],
        }],
    )
    summary = daily.run_daily(settings=settings, fetch_only=True)
    assert summary.new_rows == 1
    assert summary.errors == ["watch: gone: no greenhouse board named 'gone'"]
    (app,) = store.load_all().values()
    assert (app.company, app.role, app.canonical_key) == ("Acme", "Summer Analyst", "greenhouse:acme:7")
    assert app.source == "watch"
