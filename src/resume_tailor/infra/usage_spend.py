"""Measured model usage and its list-price cost, for Settings → AI → Usage.

Reads the per-run telemetry `infra/telemetry.py` already records (one JSON per run under
each profile's `output/telemetry/`) and prices the measured tokens with
`estimate.price_for`. Same rule as `usage_report`: a request whose provider did not
report usage is counted, never estimated; an unknown model gets tokens and no dollars.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from resume_tailor.infra.usage_report import read_runs
from resume_tailor.pipeline import estimate


def summarize(runs: list[dict]) -> dict[str, Any]:
    """Per provider/model: runs, requests, measured tokens, and USD where priceable."""
    rows: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"runs": set(), "requests": 0, "unreported": 0,
                 "input_tokens": 0, "output_tokens": 0, "usd": 0.0, "priced": True}
    )
    for run in runs:
        for request in run["requests"]:
            origin, model = request.get("origin") or "", request.get("model") or ""
            row = rows[(origin, model)]
            row["runs"].add(run.get("run_id"))
            row["requests"] += 1
            tin, tout = request.get("input_tokens"), request.get("output_tokens")
            if tin is None or tout is None:
                row["unreported"] += 1
                continue
            row["input_tokens"] += tin
            row["output_tokens"] += tout
            price = estimate.price_for(origin, model)
            if price is None:
                row["priced"] = False
            else:
                row["usd"] += (tin * price[0] + tout * price[1]) / 1_000_000
    out = []
    for (origin, model), row in sorted(rows.items()):
        local = origin in {"ollama", "lmstudio"}
        out.append({
            "origin": origin, "model": model, "runs": len(row["runs"]),
            "requests": row["requests"], "unreported": row["unreported"],
            "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
            # Ollama/LM Studio have no per-token price (local, or billed by plan).
            "billing": "no_per_token" if local else "per_token",
            "usd": round(row["usd"], 4) if row["priced"] and not local else None,
        })
    priced = [r["usd"] for r in out if r["usd"] is not None]
    return {
        "runs": len({run.get("run_id") for run in runs}),
        "models": out,
        "usd": round(sum(priced), 4) if priced else None,
        "complete": all(r["usd"] is not None or r["billing"] != "per_token" for r in out)
        and not any(r["unreported"] for r in out),
    }


def collect(outputs: list[Path], *, days: int, now: datetime | None = None) -> dict[str, Any]:
    """`summarize` over every run started in the last `days` days, across `outputs`."""
    since = ((now or datetime.now(UTC)) - timedelta(days=days)).date().isoformat()
    runs = [run for output in outputs for run in read_runs(output, since)]
    return {"days": days, **summarize(runs)}
