"""Eval harness core (`scripts/evals`): corpus, sandbox, arm runner, metrics, report.

No model calls: stages are plain functions here, and the arm runner is exercised with
`ollama:` specs that are only pinned, never called.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import arms, corpus, metrics, report, sandbox  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.content.data import Bullet  # noqa: E402
from resume_tailor.pipeline.jd import JobRequirements, Keyword  # noqa: E402

# --- corpus ---------------------------------------------------------------------------


def _run(jobs: Path, job_id: str, jd: str, *, bullets=None, ats="workday", mtime=0) -> Path:
    job = jobs / job_id
    job.mkdir(parents=True)
    (job / "jd.txt").write_text(jd, encoding="utf-8")
    (job / "requirements.json").write_text('{"title": "t", "seniority": "entry"}', "utf-8")
    (job / "bullets.json").write_text(json.dumps(bullets or {"a": "x"}), "utf-8")
    (job / "packet.json").write_text(json.dumps({"ats": ats}), "utf-8")
    os.utime(job, (mtime, mtime))
    return job


def test_saved_runs_dedupe_by_posting_keeping_the_newest(tmp_path):
    _run(tmp_path, "old", "build apis in go.", mtime=100)
    _run(tmp_path, "new", "Build  APIs in Go.", bullets={"b1": "", "b2": ""}, mtime=200)
    _run(tmp_path, "other", "Analyse ledgers. " * 200, ats="greenhouse", mtime=50)

    cases = corpus.load_saved(tmp_path)

    assert [c.case_id for c in cases] == ["new", "other"]
    assert cases[0].bullet_ids == ("b1", "b2")
    assert cases[0].ats == "workday"
    assert {"short", "short_names"} <= cases[0].tags
    assert "short" not in cases[1].tags


def test_a_run_without_its_posting_text_is_not_a_case(tmp_path):
    job = _run(tmp_path, "x", "Some posting")
    (job / "jd.txt").unlink()
    assert corpus.load_saved(tmp_path) == []


def test_fetched_postings_read_their_sidecar(tmp_path):
    (tmp_path / "bank1.txt").write_text("Financial analyst, Excel required.", "utf-8")
    (tmp_path / "bank1.json").write_text('{"group": "finance", "workspace": "nina"}', "utf-8")
    (tmp_path / "plain.txt").write_text("Registered nurse.", "utf-8")

    cases = {c.case_id: c for c in corpus.load_texts(tmp_path)}

    assert (cases["bank1"].group, cases["bank1"].workspace) == ("finance", "nina")
    assert (cases["plain"].group, cases["plain"].workspace) == ("nontech", "default")
    assert cases["plain"].job_dir is None


def _cases(spec: dict[str, int]) -> list[corpus.Case]:
    return [corpus.Case(f"{ats}{i}", "x" * 2000, ats=ats)
            for ats, n in spec.items() for i in range(n)]


def test_sample_is_deterministic_proportional_and_keeps_rare_strata():
    pool = _cases({"workday": 60, "greenhouse": 30, "lever": 2})

    first = corpus.sample(pool, 10, seed=1)

    assert first == corpus.sample(pool, 10, seed=1)
    assert len(first) == 10
    counts = {ats: sum(c.ats == ats for c in first) for ats in ("workday", "greenhouse", "lever")}
    assert counts["lever"] >= 1
    assert counts["workday"] > counts["greenhouse"] > 0


def test_sample_returns_everything_when_asked_for_more():
    pool = _cases({"workday": 3})
    assert corpus.sample(pool, None) == pool
    assert corpus.sample(pool, 50) == pool


# --- sandbox --------------------------------------------------------------------------


def test_sandbox_copies_data_but_skips_legacy_outputs_and_never_writes_live(tmp_path):
    live = tmp_path / "live"
    (live / "data" / "workspaces" / "default" / "output" / "jobs").mkdir(parents=True)
    (live / "data" / "workspaces" / "default" / "master_resume.json").write_text("{}", "utf-8")
    (live / "data" / "backups").mkdir()
    (live / "cache").mkdir()
    before = {p: p.stat().st_mtime_ns for p in live.rglob("*")}

    box = sandbox.prepare(tmp_path / "eval", live)

    assert (box / "data" / "workspaces" / "default" / "master_resume.json").exists()
    assert not (box / "data" / "workspaces" / "default" / "output").exists()
    assert not (box / "data" / "backups").exists()
    assert (box / "templates").is_dir() and (box / "output").is_dir()
    assert {p: p.stat().st_mtime_ns for p in live.rglob("*")} == before
    env = sandbox.environment(box)
    assert all(Path(v).is_relative_to(box) for k, v in env.items() if k.endswith("_DIR")
               and k != "RESUME_TAILOR_LOG_DIR")


# --- arm runner -----------------------------------------------------------------------


@pytest.fixture
def no_workspace_context(monkeypatch):
    monkeypatch.setattr(arms.config, "context_for_workspace", lambda _ws: config.default_context())


def test_each_parallel_task_sees_only_its_own_arm(tmp_path, no_workspace_context):
    cases = [corpus.Case(f"c{i}", "jd") for i in range(6)]
    arm_a = arms.Arm("a", "ollama:model-a")
    arm_b = arms.Arm("b", "ollama:model-b")
    barrier = threading.Barrier(4, timeout=10)

    def stage(_case):
        barrier.wait()  # four tasks in flight at once
        return {"model": config.model_for("rewrite"), "metrics": {}}

    tasks = [(c, a) for a in (arm_a, arm_b) for c in cases[:2]]
    records = arms.run(tasks, stage, arms.Results(tmp_path / "cases.jsonl"), workers=4,
                       out_dir=tmp_path)

    assert {r["status"] for r in records} == {"ok"}
    for r in records:
        assert r["result"]["model"] == f"model-{r['arm']}"
        assert set(r["usage"]) >= {"calls", "output_tokens", "wall_ms"}


def test_a_rerun_skips_finished_tasks_and_retries_failed_ones(tmp_path, no_workspace_context):
    results = arms.Results(tmp_path / "cases.jsonl")
    cases = [corpus.Case("good", "jd"), corpus.Case("bad", "jd")]
    arm = arms.Arm("low", "ollama:m")
    seen = []

    def flaky(case):
        seen.append(case.case_id)
        if case.case_id == "bad" and seen.count("bad") == 1:
            raise ValueError("boom")
        return {"metrics": {}}

    first = arms.run([(c, arm) for c in cases], flaky, results, workers=1, out_dir=tmp_path)
    assert {r["case"]: r["status"] for r in first} == {"good": "ok", "bad": "error"}
    assert "ValueError: boom" in next(r["error"] for r in first if r["status"] == "error")

    second = arms.run([(c, arm) for c in cases], flaky, results, workers=1, out_dir=tmp_path)
    assert [r["case"] for r in second] == ["bad"]
    assert seen == ["good", "bad", "bad"]
    assert results.done() == {"good|low|0", "bad|low|0"}


def test_rate_limits_back_off_then_give_up_without_stopping_the_batch(
    tmp_path, no_workspace_context
):
    slept: list[float] = []
    arm = arms.Arm("low", "ollama:m")

    def limited(case):
        if case.case_id == "busy":
            raise RuntimeError("429 RESOURCE_EXHAUSTED")
        return {"metrics": {}}

    records = arms.run([(corpus.Case(i, "jd"), arm) for i in ("busy", "fine")], limited,
                       arms.Results(tmp_path / "cases.jsonl"), workers=1, out_dir=tmp_path,
                       sleep=slept.append)

    assert {r["case"]: r["status"] for r in records} == {"busy": "error", "fine": "ok"}
    assert slept == list(arms.BACKOFF_SECONDS)


def test_a_truncated_results_line_is_ignored(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"key": "a|x|0", "status": "ok"}\n{"key": "b|x', "utf-8")
    assert arms.Results(path).done() == {"a|x|0"}


# --- metrics --------------------------------------------------------------------------


def _requirements(*keywords: tuple[str, str]) -> JobRequirements:
    return JobRequirements(title="Engineer", seniority="entry", keywords=[
        Keyword(phrase=p, canonical=p.lower(), importance=imp) for p, imp in keywords
    ])


def test_rewrite_metrics_count_fallbacks_mirroring_and_length():
    sources = [
        Bullet(id="a", text="Built a service in Python for billing.", tags=["python"]),
        Bullet(id="b", text="Wrote reports.", tags=[]),
    ]
    texts = {"a": "Built a Python billing service using Python.", "b": "Wrote reports."}
    reqs = _requirements(("Python", "must_have"), ("Kafka", "must_have"))

    m = metrics.rewrite_metrics(sources, texts, {"b": ["Tableau"]}, reqs, budget=202)

    assert m["fallback_rate"] == 0.5
    assert (m["must_supported"], m["must_mirrored"]) == (1, 1)  # Kafka: no bullet has it
    assert m["mirror_rate"] == 1.0
    assert m["under_length"] == 2 and m["over_length"] == 0
    assert m["changed_rate"] == 0.5


def test_rewrite_metrics_count_leftover_guard_hits():
    sources = [Bullet(id="a", text="Built a service in Python.", tags=["python"])]
    texts = {"a": "Built a Kubernetes service in Python."}
    m = metrics.rewrite_metrics(sources, texts, {}, _requirements(), budget=202)
    assert m["guard_offenders"] >= 1


def test_f1_agreement():
    assert metrics.f1({"a", "b"}, {"a", "b"}) == 1.0
    assert metrics.f1(set(), set()) == 1.0
    assert metrics.f1({"a", "b"}, {"a", "c"}) == 0.5
    assert metrics.f1({"a"}, set()) == 0.0


# --- report ---------------------------------------------------------------------------


def _record(case: str, arm: str, repeat: int, **m) -> dict:
    return {"status": "ok", "case": case, "arm": arm, "repeat": repeat,
            "result": {"metrics": m},
            "usage": {"calls": 1, "input_tokens": 1000, "output_tokens": 2000,
                      "reasoning_tokens": 0, "request_ms": 1, "wall_ms": 1000}}


def _arms(cand_fallback: float) -> dict:
    records = []
    for i in range(10):
        records.append(_record(f"c{i}", "medium", 0, fallback_rate=0.0, guard_offenders=0,
                               mirror_rate=0.8))
        records.append(_record(f"c{i}", "low", 0, fallback_rate=cand_fallback,
                               guard_offenders=0, mirror_rate=0.8))
    return report.by_arm(records)


def _verdicts(pair: tuple[str, str], a: int, b: int, tie: int) -> list[dict]:
    return [{"a": pair[0], "b": pair[1], "winner": w}
            for w, n in (("a", a), ("b", b), ("tie", tie)) for _ in range(n)]


def test_the_gate_passes_a_harmless_candidate_and_fails_a_worse_one():
    judge = _verdicts(("medium#0", "low#0"), 2, 3, 5) + _verdicts(("medium#0", "medium#1"), 2, 2, 6)
    harmless = report.gate(_arms(0.0), judge, "medium", "low", checks=report.REWRITE_CHECKS)
    assert report.verdict(harmless) == "PASS"

    worse = report.gate(_arms(0.05), judge, "medium", "low", checks=report.REWRITE_CHECKS)
    assert report.verdict(worse) == "FAIL"
    assert worse[0].passed is False


def test_the_gate_fails_when_the_judge_prefers_the_baseline_well_beyond_noise():
    judge = _verdicts(("medium#0", "low#0"), 6, 1, 3) + _verdicts(("medium#0", "medium#1"), 2, 2, 6)
    rules = report.gate(_arms(0.0), judge, "medium", "low", checks=report.REWRITE_CHECKS)
    assert rules[-1].passed is False
    assert report.verdict(rules) == "FAIL"


def test_the_gate_is_incomplete_without_the_judge():
    rules = report.gate(_arms(0.0), [], "medium", "low", checks=report.REWRITE_CHECKS)
    assert report.verdict(rules) == "INCOMPLETE"


def test_markdown_estimates_cost_from_the_price_table():
    text = report.markdown("t", _arms(0.0), ["fallback_rate"], "medium", "low",
                           rules=[], model="gemini-3.8-flash")
    # 1000 in at $0.50/M + 2000 out at $3/M per case
    assert "0.0065" in text
