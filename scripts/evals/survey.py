"""Polish on or off per model, and the cross-model survey (eval-only, no model calls).

Each model is its own eval folder (`EVAL_NAME`), seeded from the Gemini baseline's
sandbox and cases (`EVAL_FROM`), with the model set by `EVAL_LIGHT`:

* **Polish decision** (`polish_markdown`): the same frozen drafts polished at the model's
  production effort (`polish-default`) or not at all (`polish-none`). The rule is
  "remove unless it wins": polish stays only when the one-sided 95% upper bound on the
  net preference for the unpolished drafts is below 0. Fewer than
  `sequential.MIN_CASES` cases is reported as indicative, never a decision.
* **Survey** (`survey_markdown`): one row per model from its end-to-end runs, frozen
  drafts and judge verdicts against the reference model's end-to-end bullets.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from statistics import mean

from . import e2e, judge, report, sequential

POLISHED = "polish-default#0"
UNPOLISHED = "polish-none#0"
DRAFT = "draft#0"
#: One-sided alpha for the single-look polish decision.
ALPHA = 0.05
_DIFFS = ("guard_offenders", "over_length", "verb_collisions", "phrase_collisions")


def _fmt(value: float | None, spec: str = ".2f") -> str:
    return "-" if value is None or value != value else format(value, spec)


def polish_fired(grouped: dict, cases: Sequence[str]) -> tuple[int, int]:
    """(cases whose polished texts differ from their drafts, cases with both)."""
    draft, polished = grouped.get(DRAFT, {}), grouped.get(POLISHED, {})
    both = [c for c in cases if c in draft and c in polished]
    changed = sum(draft[c]["result"]["texts"] != polished[c]["result"]["texts"] for c in both)
    return changed, len(both)


def polish_decision(grouped: dict, verdicts: list[dict],
                    cases: Sequence[str]) -> tuple[str, sequential.Bound]:
    """("KEEP" | "REMOVE" | "INDICATIVE" | "INCOMPLETE", bound on the net preference for
    the unpolished drafts)."""
    scores = sequential.case_scores(verdicts, POLISHED, UNPOLISHED, cases=cases)
    bound = sequential.bounds(list(scores.values()), alpha=ALPHA)
    missing = sequential.missing_cases(cases, grouped.get(POLISHED, {}),
                                       grouped.get(UNPOLISHED, {}), verdicts=verdicts,
                                       pair=(POLISHED, UNPOLISHED))
    if missing:
        return "INCOMPLETE", bound
    if bound.n < sequential.MIN_CASES:
        return "INDICATIVE", bound
    return ("KEEP" if bound.upper == bound.upper and bound.upper < 0 else "REMOVE"), bound


def _arm_usage(arm: dict[str, dict], model: str) -> tuple[float | None, float | None, float | None]:
    """Mean (wall seconds, output tokens, dollars) per case."""
    rows = [r["usage"] for r in arm.values()]
    if not rows:
        return None, None, None
    price = report._price(model)
    cost = (mean((u["input_tokens"] * price[0] + u["output_tokens"] * price[1]) / 1e6
                 for u in rows) if price else None)
    return mean(u["wall_ms"] for u in rows) / 1000, mean(u["output_tokens"] for u in rows), cost


def polish_markdown(grouped: dict, verdicts: list[dict], cases: Sequence[str], model: str) -> str:
    decision, b = polish_decision(grouped, verdicts, cases)
    fired, both = polish_fired(grouped, cases)
    scores = sequential.case_scores(verdicts, POLISHED, UNPOLISHED, cases=cases)
    wins = sum(v == 1 for v in scores.values())
    losses = sum(v == -1 for v in scores.values())
    wall, out_tokens, cost = _arm_usage(grouped.get(POLISHED, {}), model)
    lines = [
        f"# Cosmetic polish on {model}: {decision}", "",
        f"Net preference for no polish {_fmt(b.estimate, '+.3f')} "
        f"[{_fmt(b.lower, '+.3f')}, {_fmt(b.upper, '+.3f')}] (one-sided {ALPHA:.0%} bounds, "
        f"n={b.n}): {wins} unpolished wins, {losses} polished wins, "
        f"{b.n - wins - losses} ties. Polish stays only if the upper bound is below 0.", "",
        f"Polish changed the drafts in {fired}/{both} cases; per case it cost "
        f"{_fmt(wall, '.0f')} s, {_fmt(out_tokens, '.0f')} output tokens, "
        f"${_fmt(cost, '.4f')}.", "",
        "| Metric (no polish minus polish, per resume) | mean |", "|---|---|",
    ]
    polished, plain = grouped.get(POLISHED, {}), grouped.get(UNPOLISHED, {})
    for metric in _DIFFS:
        diffs = [plain[c]["result"]["metrics"][metric] - polished[c]["result"]["metrics"][metric]
                 for c in cases if c in polished and c in plain]
        lines.append(f"| {metric} | {_fmt(mean(diffs) if diffs else None, '+.2f')} |")
    return "\n".join(lines) + "\n"


# -- survey ----------------------------------------------------------------------------


def _records(eval_dir: Path) -> dict[str, dict[str, dict]]:
    path = eval_dir / "cases.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()
            if line.strip()] if path.exists() else []
    return report.by_arm(rows)


def _draft_mean(drafts: list[dict], metric: str) -> float | None:
    return mean(d["result"]["metrics"][metric] for d in drafts) if drafts else None


def survey_row(eval_dir: Path, arm: str = "run") -> dict:
    meta = json.loads((eval_dir / "meta.json").read_text("utf-8"))
    runs = e2e.load(eval_dir / "e2e", arm)
    ok = [r for r in runs.values() if not e2e.failed(r)]
    verdicts = judge.Verdicts(judge.verdicts_file(eval_dir / "e2e")).records()
    vs_ref = sequential.case_scores(verdicts, "base", arm)
    grouped = _records(eval_dir)
    drafts = list(grouped.get(DRAFT, {}).values())
    cases = meta["cases"]
    decision, bound = polish_decision(grouped, judge.Verdicts(
        judge.verdicts_file(eval_dir)).records(), cases)
    fired, both = polish_fired(grouped, cases)

    def stage_seconds(r: dict) -> dict[str, float]:
        return {s: u["request_ms"] / 1000 for s, u in (r.get("usage_by_stage") or {}).items()}

    stages = sorted({s for r in runs.values() for s in stage_seconds(r)})
    return {
        "model": meta["model"], "runs": len(runs), "ok": len(ok),
        "errors": [(r["case"], (r.get("error") or f"exit {r.get('exit')}")[-200:])
                   for r in runs.values() if e2e.failed(r)],
        "fill": mean(r["fill"] for r in ok) if ok else None,
        "widows": mean(r["widows"] for r in ok) if ok else None,
        "rounds": mean(r["rounds"] for r in ok) if ok else None,
        "dropped": mean(r["dropped"] for r in ok) if ok else None,
        "wall": mean(r["wall_s"] for r in runs.values()) if runs else None,
        "stage_s": {s: mean(stage_seconds(r).get(s, 0) for r in runs.values()) for s in stages},
        "retries": mean(sum(u.get("retries", 0) for u in (r.get("usage_by_stage") or {}).values())
                        for r in runs.values()) if runs else None,
        "vs_ref": (mean(vs_ref.values()) if vs_ref else None, len(vs_ref)),
        "fallback": _draft_mean(drafts, "fallback_rate"),
        "offenders": _draft_mean(drafts, "guard_offenders"),
        "polish": (decision, bound.estimate, bound.n, fired, both),
    }


def survey_markdown(eval_dirs: Sequence[Path], arm: str = "run") -> str:
    rows = [survey_row(d, arm) for d in eval_dirs if (d / "meta.json").exists()]
    lines = ["# Model survey", "",
             "| Model | ok runs | fill | widows | fit rounds | dropped | mean run s | "
             "retries/run | judge vs reference | draft fallback rate | guard offenders | "
             "polish (net for none, n, fired) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        net, n = r["vs_ref"]
        decision, est, pn, fired, both = r["polish"]
        lines.append(
            f"| {r['model']} | {r['ok']}/{r['runs']} | {_fmt(r['fill'])} | {_fmt(r['widows'])} | "
            f"{_fmt(r['rounds'])} | {_fmt(r['dropped'])} | {_fmt(r['wall'], '.0f')} | "
            f"{_fmt(r['retries'], '.1f')} | {_fmt(net, '+.2f')} (n={n}) | "
            f"{_fmt(r['fallback'])} | {_fmt(r['offenders'])} | "
            f"{decision} {_fmt(est, '+.2f')}, {pn}, {fired}/{both} |")
    lines += ["", "Request seconds per run, by stage:", ""]
    for r in rows:
        parts = ", ".join(f"{s} {v:.0f}" for s, v in r["stage_s"].items())
        lines.append(f"- {r['model']}: {parts or '-'}")
    errors = [(r["model"], c, e) for r in rows for c, e in r["errors"]]
    if errors:
        lines += ["", "Failed runs:", ""] + [f"- {m} {c}: `{e.splitlines()[-1] if e else ''}`"
                                             for m, c, e in errors]
    return "\n".join(lines) + "\n"
