"""Summarize local measured usage; old runs and unknown usage are never estimated."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    point = (len(ordered) - 1) * q
    lo = int(point)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo), 3)


def _timing(values: list[float]) -> dict:
    return {
        "count": len(values),
        "median_ms": percentile(values, 0.5),
        "p90_ms": percentile(values, 0.9),
    }


def read_runs(output: Path, since: str | None = None) -> list[dict]:
    result = []
    for path in sorted((output / "telemetry").glob("*.json")):
        try:
            run = json.loads(path.read_text("utf-8"))
            if run.get("schema_version") != 1:
                continue
            if since and run["started_at"][:10] < since:
                continue
            if not all(isinstance(run.get(key), list) for key in ("requests", "spans", "events")):
                continue
            result.append(run)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return result


def read_consumption(output: Path) -> list[dict]:
    path = output / "telemetry" / "artifact_usage.jsonl"
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        try:
            row = json.loads(line)
            if row.get("artifact") == "skills" and row.get("action") in {
                "copy",
                "download",
                "autofill",
            }:
                result.append(row)
        except (ValueError, AttributeError):
            continue
    return result


def _skills_delay(run: dict) -> float:
    spans = [s for s in run["spans"] if s["kind"] == "stage"]
    ends = [(s["stage"], s["start_ms"] + s["duration_ms"]) for s in spans]
    skill_end = max((end for name, end in ends if name == "skills"), default=0)
    other_end = max((end for name, end in ends if name != "skills"), default=0)
    return max(0, skill_end - max(other_end, run.get("resume_ready_ms") or 0))


def _summarize(runs: list[dict], consumption: list[dict], now: datetime) -> dict:
    requests = [r for run in runs for r in run["requests"]]
    tokens = {
        key: sum(r[key] for r in requests if r.get(key) is not None)
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_creation_tokens",
            "reasoning_tokens",
        )
    }
    known = sum(
        r.get("input_tokens") is not None and r.get("output_tokens") is not None for r in requests
    )
    stages: dict[str, list[float]] = defaultdict(list)
    operations: dict[str, list[float]] = defaultdict(list)
    numbers = dict.fromkeys(("number_omissions", "number_repairs", "number_fallbacks"), 0)
    cache: dict[str, dict[str, int]] = defaultdict(lambda: {"hits": 0, "misses": 0, "skips": 0})
    agreements = []
    cold_extracts = 0
    for run in runs:
        for span in run["spans"]:
            if span["kind"] == "stage":
                stages[span["stage"]].append(span["duration_ms"])
                operations[f"{span['stage']}/{span['operation']}"].append(span["duration_ms"])
        # One cache observation per stage per run; consensus emits one miss per vote.
        by_stage: dict[str, list[dict]] = defaultdict(list)
        for event in run["events"]:
            by_stage[event["stage"]].append(event)
            for key in numbers:
                numbers[key] += event.get(key, 0)
            if "sample_agreement" in event:
                agreements.append(event["sample_agreement"])
        for stage, events in by_stage.items():
            if any(e.get("skipped") for e in events):
                cache[stage]["skips"] += 1
            elif any(e.get("cached") is False for e in events):
                cache[stage]["misses"] += 1
            elif any(e.get("cached") is True for e in events):
                cache[stage]["hits"] += 1
        cold_extracts += any(
            e["stage"] == "extract" and e.get("cached") is False for e in run["events"]
        )
    succeeded = [r for r in runs if r["status"] == "succeeded"]
    mature = [
        r
        for r in succeeded
        if r.get("source") == "web"
        and any(e["stage"] == "skills" and e.get("available") for e in r["events"])
        and datetime.fromisoformat(r["finished_at"]) <= now - timedelta(days=7)
    ]
    used = 0
    matched = []
    for run in mature:
        start = datetime.fromisoformat(run["finished_at"])
        events = [
            e
            for e in consumption
            if e.get("archive_id") == run.get("archive_id")
            and start <= datetime.fromisoformat(e["at"]) <= start + timedelta(days=7)
        ]
        used += bool(events)
        matched.extend(events)
    skill_tokens = sum(
        (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
        for r in requests
        if r["stage"] == "skills"
    )
    total_tokens = tokens["input_tokens"] + tokens["output_tokens"]
    total_time = sum(r.get("completion_ms", 0) for r in succeeded)
    tail = sum(_skills_delay(r) for r in succeeded)
    share = skill_tokens / total_tokens if total_tokens else None
    rate = used / len(mature) if mature else None
    enough = len(succeeded) >= 30 and cold_extracts >= 10
    sufficient_skills = len(mature) >= 30 and known == len(requests) and bool(requests)
    skills_decision = "collect_more_data"
    if sufficient_skills and rate is not None:
        skills_decision = (
            "evaluate_on_demand"
            if rate <= 0.2
            and ((share is not None and share >= 0.1) or (total_time and tail / total_time >= 0.1))
            else "retain_automatic_generation"
        )
    return {
        "runs": len(runs),
        "succeeded": len(succeeded),
        "physical_requests": len(requests),
        "logical_calls": sum(s["kind"] == "llm_call" for r in runs for s in r["spans"]),
        "known_usage_requests": known,
        "unknown_usage_requests": len(requests) - known,
        "known_tokens": tokens,
        "resume_ready": _timing(
            [r["resume_ready_ms"] for r in succeeded if r.get("resume_ready_ms") is not None]
        ),
        "completion": _timing([r["completion_ms"] for r in succeeded]),
        "queue": _timing([r["queue_ms"] for r in requests]),
        "request": _timing([r["request_ms"] for r in requests]),
        "stages": {k: _timing(v) for k, v in sorted(stages.items())},
        "operations": {k: _timing(v) for k, v in sorted(operations.items())},
        "rewrite_numbers": numbers,
        "cache": dict(cache),
        "retry_requests": sum(r["reason"] != "generation" for r in requests),
        "request_reasons": dict(Counter(r["reason"] for r in requests)),
        "cold_extractions": cold_extracts,
        "extraction_agreement_median": percentile(agreements, 0.5),
        "jd_voting_decision": "paired_quality_comparison_required"
        if enough
        else "collect_more_data",
        "skills": {
            "mature_eligible_runs": len(mature),
            "consuming_runs": used,
            "observed_consumption_rate": rate,
            "events": len(matched),
            "known_token_share": share,
            "tail_delay_ms": round(tail, 3),
            "decision": skills_decision,
        },
    }


def summarize(runs: list[dict], consumption: list[dict], *, now: datetime | None = None) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        routing = {
            k: v
            for k, v in run.get("routing", {}).items()
            if k in {"extract", "score", "rewrite", "facets", "skills", "expand", "cover"}
        }
        cache = next(
            (
                e.get("cached")
                for e in run["events"]
                if e["stage"] == "extract" and e.get("cached") is not None
            ),
            None,
        )
        key = json.dumps(
            {"routing": routing, "versions": run.get("versions", {}), "extraction_cached": cache},
            sort_keys=True,
        )
        groups[key].append(run)
    # Review gates span cache states, while latency cohorts keep them separate.
    cohorts: dict[str, list[dict]] = defaultdict(list)
    for key, rows in groups.items():
        info = json.loads(key)
        info.pop("extraction_cached")
        cohorts[json.dumps(info, sort_keys=True)].extend(rows)
    instant = now or datetime.now(UTC)
    return {
        "schema_version": 1,
        "observed_runs": len(runs),
        "groups": [
            {**json.loads(k), **_summarize(v, consumption, instant)} for k, v in groups.items()
        ],
        "decisions": [
            {**json.loads(k), **_summarize(v, consumption, instant)} for k, v in cohorts.items()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    from .. import config, workspace

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace")
    parser.add_argument(
        "--since", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    workspace.bootstrap(workspace_id=args.workspace)
    result = summarize(
        read_runs(config.OUTPUT_DIR, args.since), read_consumption(config.OUTPUT_DIR)
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"Measured runs: {result['observed_runs']}")
    for i, group in enumerate(result["groups"], 1):
        print(f"\nCohort {i}: {group['runs']} runs; extraction cached={group['extraction_cached']}")
        print(
            "Routing: "
            + ", ".join(f"{p}={r['origin']}:{r['model']}" for p, r in group["routing"].items())
        )
        print(f"Versions: {group['versions']}")
        print(f"Completion: {group['completion']}; resume ready: {group['resume_ready']}")
        print(
            f"Known tokens: {group['known_tokens']}; "
            f"unknown usage: {group['unknown_usage_requests']}"
        )
        print(
            f"Calls: {group['logical_calls']}; requests: {group['physical_requests']}; "
            f"retries: {group['retry_requests']} ({group['request_reasons']})"
        )
        print(f"Stage timings: {group['stages']}; queue: {group['queue']}")
        print(
            f"Operation timings: {group['operations']}; "
            f"number retention: {group['rewrite_numbers']}"
        )
        print(f"Cache: {group['cache']}; skills: {group['skills']}")
    for decision in result["decisions"]:
        print(
            f"\nJD voting: {decision['jd_voting_decision']}; "
            f"skills: {decision['skills']['decision']}"
        )
    print("Observed skills use is incomplete; JD vote changes require paired quality review.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
