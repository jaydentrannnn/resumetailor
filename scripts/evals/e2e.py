"""End-to-end arm runs through the CLI fit loop, one OS process per worker.

An arm is a name plus environment (`variants.CLAUSE_ENV`, `variants.POLISH_ENV`), so no
worker ever shares an in-process patch with another. Workers claim postings with
exclusive-create files (`.claim-<case>`), so several can share an arm without
duplicating work. Each finished posting appends one record to `<arm>/results.jsonl`:
pages, fill, widows, dropped bullets, fit rounds, whether the page count was only
estimated, the final bullets, cost per pipeline stage and wall time. Run arms one after
another, baseline first, so later arms reuse the extraction and scoring caches the first
one filled. That reuse is why the cost gate leaves out `CACHED_STAGES`: the first arm
pays for them and the second does not, which says nothing about the change under test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from . import arms as arms_mod
from . import report, sequential

#: Stages cached per posting: whichever arm runs first pays for them, so they are left
#: out of the cost gate and reported separately (`total` vs `gated` cost).
CACHED_STAGES = frozenset({"extract", "score", "facets", "skills"})


def stage_usage(collector_data: dict) -> dict[str, dict[str, float]]:
    """`{stage: {calls, input_tokens, output_tokens, request_ms}}` over the run's requests."""
    out: dict[str, dict[str, float]] = {}
    for r in collector_data.get("requests", []):
        row = out.setdefault(r.get("stage") or "unknown", dict.fromkeys(
            ("calls", "input_tokens", "output_tokens", "request_ms"), 0))
        row["calls"] += 1
        for key in ("input_tokens", "output_tokens", "request_ms"):
            row[key] += r.get(key) or 0
    return out


def record(case: str, arm: str, *, code: int, result: Any, usage: dict, wall_s: float,
           error: str | None, target_pages: int,
           usage_by_stage: dict[str, dict[str, float]] | None = None) -> dict:
    """One posting's outcome. `result` is the run's `FitResult`, or None when the run
    failed before fitting."""
    out: dict[str, Any] = {"case": case, "arm": arm, "exit": code, "error": error,
                           "wall_s": wall_s, "usage": usage,
                           "usage_by_stage": usage_by_stage or {}}
    if result is not None:
        out.update({
            "pages": result.pages,
            "estimated": bool(result.pages_are_estimated),
            "over_target": result.pages > target_pages,
            "fill": result.fill_ratio,
            "widows": result.widows_remaining,
            "dropped": len(result.dropped),
            "rounds": result.iterations,
            "bullets": dict(result.bullets),
        })
    return out


def failed(r: dict) -> bool:
    """A run that errored, exited non-zero, never fitted, or only estimated its pages."""
    return bool(r.get("error")) or r.get("exit") != 0 or "pages" not in r or r["estimated"]


def run_worker(out_dir: Path, arm: str, cases: Sequence[tuple[str, str]], *,
               spec: Any, effort: Any, workspace: str = "default") -> None:
    """Inside a worker process (sandbox env already applied): run each unclaimed
    `(case id, posting text)` through the CLI at its default page target and append its
    record. The fit result and the CLI's own telemetry collector are captured by
    wrapping `fit.fit` and `telemetry.recording` in this process only."""
    from contextlib import contextmanager

    from resume_tailor import config
    from resume_tailor.cli import run as cli_run
    from resume_tailor.infra import telemetry
    from resume_tailor.pipeline import fit

    from . import variants

    variants.install()
    captured: dict[str, Any] = {}
    original_fit, original_recording = fit.fit, telemetry.recording

    def capture(*args, **kwargs):
        captured["result"] = original_fit(*args, **kwargs)
        return captured["result"]

    @contextmanager
    def recording(*args, **kwargs):
        with original_recording(*args, **kwargs) as collector:
            captured["collector"] = collector
            yield collector

    fit.fit, telemetry.recording = capture, recording
    target_pages = config.DEFAULT_PAGE_TARGET
    arm_dir = out_dir / arm
    arm_dir.mkdir(parents=True, exist_ok=True)
    overrides = dict.fromkeys(config.PURPOSES, spec)
    for case_id, jd_text in cases:
        try:
            os.close(os.open(arm_dir / f".claim-{case_id}", os.O_CREAT | os.O_EXCL))
        except FileExistsError:
            continue
        jd = arm_dir / f"{case_id}.jd.txt"
        jd.write_text(jd_text, encoding="utf-8")
        argv = ["--jd", str(jd), "--workspace", workspace, "--no-expand",
                "--no-cover-letter", "--out", str(arm_dir / f"{case_id}.docx")]
        captured.clear()
        started, error = time.perf_counter(), None
        try:
            with config.pinned("ollama", overrides=overrides, effort=effort):
                code = cli_run.main(argv)
        except BaseException:  # noqa: BLE001 - record the failure, keep going
            code, error = -1, traceback.format_exc()[-1500:]
        wall = round(time.perf_counter() - started, 1)
        collector = captured.get("collector")
        rec = record(case_id, arm, code=code, result=captured.get("result"),
                     usage=arms_mod.usage(collector.data) if collector else {},
                     usage_by_stage=stage_usage(collector.data) if collector else {},
                     wall_s=wall, error=error, target_pages=target_pages)
        with (arm_dir / "results.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{arm} {case_id} exit={code} {wall}s", flush=True)


def launch(command: Sequence[str], env: dict[str, str], workers: int) -> int:
    """Start `workers` copies of `command` (each its own process) and wait for all;
    return the number that exited non-zero."""
    procs = [subprocess.Popen(list(command), env={**os.environ, **env})
             for _ in range(max(1, workers))]
    return sum(1 for p in procs if p.wait() != 0)


def load(out_dir: Path, arm: str) -> dict[str, dict]:
    """`{case: record}` for one arm; the last record per case wins."""
    path = out_dir / arm / "results.jsonl"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        out[r["case"]] = r
    return out


def _cost(r: dict, model: str, *, gated: bool = False) -> float | None:
    """Model cost of one run; `gated` leaves out `CACHED_STAGES`. None when a gated cost
    is asked of a record without per-stage usage."""
    price = report._price(model)
    if price is None:
        return None
    if gated:
        stages = r.get("usage_by_stage")
        if not stages:
            return None
        rows = [u for s, u in stages.items() if s not in CACHED_STAGES]
    else:
        rows = [r.get("usage") or {}]
    return sum(u.get("input_tokens", 0) * price[0] + u.get("output_tokens", 0) * price[1]
               for u in rows) / 1e6


def _mean(rows: list[dict], key: str) -> float:
    values = [r[key] for r in rows if r.get(key) is not None]
    return mean(values) if values else float("nan")


def gates(cases: Sequence[str], base: dict[str, dict], cand: dict[str, dict],
          judge_scores: dict[str, int], *, model: str,
          cost_limit: float) -> list[tuple[str, str, bool]]:
    """The pre-registered ship gates over the declared `cases`: `(gate, detail, passed)`.

    Nothing is decided on whatever happened to finish: a case missing from either arm,
    or a pair of successful runs without a judge verdict, fails its gate.
    """
    absent = [k for k in cases if k not in base or k not in cand]
    b = [base[k] for k in cases if k in base]
    c = [cand[k] for k in cases if k in cand]
    ok_b = [r for r in b if not failed(r)]
    ok_c = [r for r in c if not failed(r)]
    both = [k for k in cases if k in base and k in cand
            and not failed(base[k]) and not failed(cand[k])]
    pb, pc = [base[k] for k in both], [cand[k] for k in both]
    out = [("every case ran in both arms",
            f"{len(cases) - len(absent)}/{len(cases)}" + (f" (missing {', '.join(absent)})"
                                                          if absent else ""), not absent)]
    fails = (len(b) - len(ok_b), len(c) - len(ok_c))
    out.append(("failed or estimated runs", f"{fails[0]} -> {fails[1]}", fails[1] <= fails[0]))
    over = (sum(1 for r in ok_b if r["over_target"]), sum(1 for r in ok_c if r["over_target"]))
    out.append(("cases over the page target", f"{over[0]} -> {over[1]}", over[1] <= over[0]))
    for key, limit, label, higher_is_worse in (
        ("fill", -0.02, "mean fill change >= -2 points", False),
        ("widows", 0.5, "mean widows-remaining change <= +0.5", True),
        ("dropped", 0.5, "mean dropped-bullet change <= +0.5", True),
        ("rounds", 0.5, "mean fit-round change <= +0.5", True),
    ):
        d = _mean(pc, key) - _mean(pb, key)
        passed = d <= limit if higher_is_worse else d >= limit
        detail = f"{_mean(pb, key):.3f} -> {_mean(pc, key):.3f} ({d:+.3f}, n={len(both)})"
        out.append((label, detail, passed))
    scores = {k: judge_scores[k] for k in both if k in judge_scores}
    unjudged = [k for k in both if k not in judge_scores]
    net = mean(scores.values()) if scores else float("nan")
    detail = f"{net:+.3f} (n={len(scores)})" + (
        f", no verdict for {', '.join(unjudged)}" if unjudged else "")
    out.append(("judge net preference >= -10 points", detail,
                not unjudged and net >= -0.10))
    ran = [k for k in cases if k in base and k in cand]
    gated = sequential.ratio_bounds([(_cost(base[k], model, gated=True),
                                      _cost(cand[k], model, gated=True)) for k in ran])
    total = sequential.ratio_bounds([(_cost(base[k], model), _cost(cand[k], model))
                                     for k in ran])
    out.append((f"cost without cached stages <= +{cost_limit:.0%}",
                f"{gated.estimate:+.1%} (n={gated.n}; with the first arm's cache fills "
                f"{total.estimate:+.1%})", gated.n == len(ran) and gated.estimate <= cost_limit))
    return out


def runtime(rows: dict[str, dict]) -> str:
    """Mean wall time, and the part spent in requests of uncached stages."""
    walls = [r["wall_s"] for r in rows.values()]
    if not walls:
        return "-"
    uncached = [sum(u["request_ms"] for s, u in r["usage_by_stage"].items()
                    if s not in CACHED_STAGES) / 1000
                for r in rows.values() if r.get("usage_by_stage")]
    tail = (f" ({mean(uncached):.0f}s in uncached-stage requests)"
            if len(uncached) == len(walls) else "")
    return f"mean {mean(walls):.0f}s over {len(walls)}{tail}"


def worker_command(script: Path, *args: str) -> list[str]:
    return [sys.executable, str(script), *args]
