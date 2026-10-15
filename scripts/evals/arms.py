"""Run one stage over (case x arm) in parallel, resumably, with per-call telemetry.

An arm is a model spec plus an effort. Every task runs inside its own copy of the
config run context (`config.use_context` + `config.pinned`), so parallel cases never
see each other's routing, guidance or styles. Results append to `cases.jsonl`; a rerun
skips every (case, arm, repeat) key already recorded with status "ok".
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.infra import telemetry

from .corpus import Case

#: Substrings of a provider error that mean "slow down", not "this case is broken".
_RATE_LIMITED = ("429", "resource_exhausted", "rate limit", "quota")
BACKOFF_SECONDS = (20.0, 60.0, 120.0)


@dataclass(frozen=True)
class Arm:
    """`effort` is one effort for every stage or a per-step map (`config.EFFORT_STEPS`)."""

    name: str
    spec: config.ModelSpec
    effort: str | dict[str, str] | None = None
    repeat: int = 0

    def key(self, case: Case) -> str:
        return f"{case.case_id}|{self.name}|{self.repeat}"


Stage = Callable[[Case], dict[str, Any]]
#: Wraps each task (e.g. binds the run's guidance); must yield inside the run context.
Setup = Callable[[Case], Any]


class Results:
    """Append-only JSONL of task records; thread-safe."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a line cut short by a crash
        return out

    def done(self) -> set[str]:
        return {r["key"] for r in self.records() if r.get("status") == "ok"}

    def append(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def usage(collector_data: dict) -> dict[str, float]:
    """Token and latency totals over every request the task made."""
    requests = collector_data.get("requests", [])

    def total(name: str) -> int:
        return sum(r.get(name) or 0 for r in requests)

    return {
        "calls": len(requests),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "reasoning_tokens": total("reasoning_tokens"),
        "request_ms": total("request_ms"),
    }


def _rate_limited(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMITED)


def _attempt(case: Case, arm: Arm, stage: Stage, setup: Setup | None, out_dir: Path) -> dict:
    overrides = dict.fromkeys(config.PURPOSES, arm.spec)
    run_id = arm.key(case).replace("|", "__")
    with config.use_context(config.context_for_workspace(case.workspace)):
        if setup is not None:
            setup(case)
        with config.pinned("ollama", overrides=overrides, effort=arm.effort), \
                telemetry.recording(out_dir, run_id=run_id, source="eval") as collector:
            started = time.perf_counter()
            result = stage(case)
            wall_ms = round((time.perf_counter() - started) * 1000)
    return {"result": result, "usage": {**usage(collector.data), "wall_ms": wall_ms}}


def _task(case, arm, stage, setup, out_dir, sleep) -> dict:
    record = {"key": arm.key(case), "case": case.case_id, "arm": arm.name,
              "repeat": arm.repeat, "group": case.group, "ats": case.ats,
              "tags": sorted(case.tags)}
    for wait in (*BACKOFF_SECONDS, None):
        try:
            return {**record, "status": "ok", **_attempt(case, arm, stage, setup, out_dir)}
        except Exception as exc:  # noqa: BLE001 - one bad case must never stop the batch
            if wait is not None and _rate_limited(exc):
                sleep(wait)
                continue
            return {**record, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    raise AssertionError("unreachable")


def run(
    tasks: Iterable[tuple[Case, Arm]],
    stage: Stage,
    results: Results,
    *,
    setup: Setup | None = None,
    workers: int = 4,
    out_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[dict], None] | None = None,
) -> list[dict]:
    """Run every task not already done; return the new records (errors included)."""
    done = results.done()
    todo = [(c, a) for c, a in tasks if a.key(c) not in done]
    out_dir = out_dir or results.path.parent
    new: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            config.submit_in_context(pool, _task, case, arm, stage, setup, out_dir, sleep)
            for case, arm in todo
        ]
        for future in as_completed(futures):
            record = future.result()
            results.append(record)
            new.append(record)
            if progress is not None:
                progress(record)
    return new
