"""Bounded parallel stages keep ordering, workspace state, and conversion safe."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from resume_tailor import config, convert, jd
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.web import jobs as jobs_mod
from resume_tailor.web.jobs import JobQueue
from resume_tailor.web.schemas import JobSettings


def test_extraction_votes_overlap_and_keep_submission_order(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    replies = [
        JobRequirements(
            title=f"Title {i}", seniority="entry",
            keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
        )
        for i in range(3)
    ]
    barrier = threading.Barrier(3)
    # Each vote's reply is fixed by its submission order (not by which thread reaches the
    # model first, which the scheduler decides); later votes finish first.
    submitted = iter(range(3))
    current = threading.local()
    calls = []
    submit = config.submit_in_context

    def numbered(executor, fn, *args, **kwargs):
        index = next(submitted)

        def run(*a, **k):
            current.index = index
            return fn(*a, **k)

        return submit(executor, run, *args, **kwargs)

    class Client:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            index = current.index
            calls.append(index)
            barrier.wait(timeout=5)
            time.sleep(0.03 * (2 - index))
            return SimpleNamespace(parsed_output=replies[index], stop_reason="end_turn")

    monkeypatch.setattr(config, "submit_in_context", numbered)
    monkeypatch.setattr(jd.llm, "client_for", lambda purpose: Client())
    result = jd.extract_consensus("Python required.", runs=3, use_cache=False)
    serial, _ = jd._vote(replies, None)
    assert result == serial
    assert sorted(calls) == [0, 1, 2]


def test_two_workspace_jobs_overlap_without_crossing_contexts(monkeypatch, tmp_path):
    for name, path in (
        ("DATA_ROOT", tmp_path / "data"),
        ("TEMPLATES_ROOT", tmp_path / "templates"),
        ("OUTPUT_ROOT", tmp_path / "output"),
        ("CACHE_ROOT", tmp_path / "cache"),
    ):
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(jobs_mod.housekeeping, "run", lambda: None)
    barrier = threading.Barrier(2)
    observed: dict[str, tuple[Path, str]] = {}
    queue = JobQueue()

    def stage(job):
        config.resolve(job.settings.model)
        barrier.wait(timeout=5)
        output = config.OUTPUT_DIR / "jobs" / job.job_id
        output.mkdir(parents=True)
        (output / "stage.txt").write_text(job.workspace_id or "")
        job.out_dir = output
        observed[job.workspace_id] = (output, config.backend_for("rewrite").origin)

    monkeypatch.setattr(queue, "_execute_in_context", stage)
    with config.use_context(config.context_for_workspace("alpha")):
        first, _ = queue.submit("first", JobSettings(model="claude"))
    with config.use_context(config.context_for_workspace("beta")):
        second, _ = queue.submit("second", JobSettings(model="ollama"))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (
        first.status not in {"succeeded", "failed"} or second.status not in {"succeeded", "failed"}
    ):
        time.sleep(0.01)
    assert first.status == second.status == "succeeded"
    assert observed["alpha"] == (
        config.workspace_paths("alpha")["OUTPUT_DIR"] / "jobs" / first.job_id,
        "anthropic",
    )
    assert observed["beta"] == (
        config.workspace_paths("beta")["OUTPUT_DIR"] / "jobs" / second.job_id,
        "ollama",
    )
    assert first.out_dir.joinpath("stage.txt").read_text() == "alpha"
    assert second.out_dir.joinpath("stage.txt").read_text() == "beta"
    assert not queue.busy()


def test_pdf_conversion_is_serialized(monkeypatch, tmp_path):
    in_flight = 0
    peak = 0
    lock = threading.Lock()
    start = threading.Barrier(2)

    def fake_convert(docx_path, pdf_path, *, keep_active):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        pdf_path.write_bytes(b"pdf")
        with lock:
            in_flight -= 1

    monkeypatch.setitem(convert._BACKENDS, "word", fake_convert)

    def call(index):
        start.wait(timeout=5)
        return convert.convert(tmp_path / f"{index}.docx", tmp_path / f"{index}.pdf", backend="word")

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(call, range(2)))
    assert all(path.exists() for path in paths)
    assert peak == 1
