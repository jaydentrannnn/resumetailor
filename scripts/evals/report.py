"""Paired arm comparisons, cost, judge tallies, and the PASS/FAIL decision rules.

Arms are labelled `<name>#<repeat>`: the baseline is `<base>#0`, the candidate
`<cand>#0`, and the noise control `<base>#1` (the baseline run again). A difference
only means something when it beats baseline-vs-control.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, median

#: Assumed list prices, USD per million tokens (input, output incl. reasoning). An
#: estimate for the report only; edit when the provider's pricing changes.
PRICES: dict[str, tuple[float, float]] = {
    "gemini": (0.50, 3.00),
    "claude-haiku": (1.00, 5.00),
    "gpt-5-mini": (0.25, 2.00),
}


def label(record: dict) -> str:
    return f"{record['arm']}#{record.get('repeat', 0)}"


def by_arm(records: list[dict]) -> dict[str, dict[str, dict]]:
    """`{arm label: {case id: record}}` over successful records; the last one wins."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in records:
        if r.get("status") == "ok":
            out[label(r)][r["case"]] = r
    return out


def _bootstrap_ci(diffs: list[float], *, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if len(diffs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


@dataclass
class Paired:
    metric: str
    n: int
    a: float
    b: float
    diff: float
    ci: tuple[float, float]


def paired(arms: dict[str, dict[str, dict]], metric: str, a: str, b: str) -> Paired | None:
    """Mean of `metric` on the cases both arms completed, and the b - a difference."""
    left, right = arms.get(a, {}), arms.get(b, {})
    common = sorted(set(left) & set(right))
    values = [
        (left[c]["result"]["metrics"].get(metric), right[c]["result"]["metrics"].get(metric))
        for c in common
    ]
    values = [(x, y) for x, y in values if x is not None and y is not None]
    if not values:
        return None
    diffs = [y - x for x, y in values]
    return Paired(metric, len(values), mean(x for x, _ in values),
                  mean(y for _, y in values), mean(diffs), _bootstrap_ci(diffs))


def _price(model: str) -> tuple[float, float] | None:
    for prefix, price in PRICES.items():
        if prefix in model:
            return price
    return None


def usage_summary(arm: dict[str, dict], model: str = "") -> dict[str, float | None]:
    usages = [r["usage"] for r in arm.values()]
    if not usages:
        return {}
    walls = sorted(u["wall_ms"] for u in usages)
    out = {
        "cases": len(usages),
        "wall_p50_s": median(walls) / 1000,
        "wall_p90_s": walls[min(len(walls) - 1, int(0.9 * len(walls)))] / 1000,
        "calls": mean(u["calls"] for u in usages),
        "output_tokens": mean(u["output_tokens"] for u in usages),
        "reasoning_tokens": mean(u["reasoning_tokens"] for u in usages),
        "input_tokens": mean(u["input_tokens"] for u in usages),
    }
    price = _price(model)
    out["usd_per_case"] = (
        (out["input_tokens"] * price[0] + out["output_tokens"] * price[1]) / 1e6
        if price else None
    )
    return out


def judge_tally(verdicts: list[dict], a: str, b: str) -> dict[str, int]:
    """Consistent wins for each side and ties, for the pair (`a`, `b`)."""
    tally = {"a": 0, "b": 0, "tie": 0}
    for v in verdicts:
        # A judgement that errored has no winner and counts for neither side.
        if (v.get("a"), v.get("b")) == (a, b) and v.get("winner") in tally:
            tally[v["winner"]] += 1
    return tally


def loss_rate(tally: dict[str, int]) -> float | None:
    """How often `b` (the challenger) lost outright."""
    total = sum(tally.values())
    return tally["a"] / total if total else None


@dataclass
class Rule:
    text: str
    passed: bool | None  # None: not enough data to decide
    detail: str


def _within(p: Paired | None, limit: float, text: str, *, higher_is_worse: bool) -> Rule:
    if p is None:
        return Rule(text, None, "no paired cases")
    worse = p.diff if higher_is_worse else -p.diff
    return Rule(text, worse <= limit, f"{p.a:.3f} -> {p.b:.3f} (diff {p.diff:+.3f}, n={p.n})")


def gate(
    arms: dict[str, dict[str, dict]], verdicts: list[dict], base: str, cand: str,
    *, checks: list[tuple[str, float, bool, str]], judge_margin: float = 0.10,
) -> list[Rule]:
    """Every `(metric, allowed worsening, higher_is_worse, text)` check, then the judge.

    The allowed worsening grows by the control's own drift on that metric, so noise the
    baseline shows against itself is never charged to the candidate.
    """
    b0, c0, b1 = f"{base}#0", f"{cand}#0", f"{base}#1"
    rules = []
    for metric, limit, higher_is_worse, text in checks:
        control = paired(arms, metric, b0, b1)
        slack = abs(control.diff) if control else 0.0
        rules.append(_within(paired(arms, metric, b0, c0), limit + slack, text,
                             higher_is_worse=higher_is_worse))
    cand_loss = loss_rate(judge_tally(verdicts, b0, c0))
    noise_loss = loss_rate(judge_tally(verdicts, b0, b1))
    text = f"judge: {cand} loses no more often than the control, +{judge_margin:.0%}"
    if cand_loss is None or noise_loss is None:
        rules.append(Rule(text, None, "judge not run on both pairs"))
    else:
        rules.append(Rule(text, cand_loss <= noise_loss + judge_margin,
                          f"{cand} lost {cand_loss:.0%}, control lost {noise_loss:.0%}"))
    return rules


REWRITE_CHECKS = [
    ("fallback_rate", 0.01, True, "fallback rate rises <= 1 point"),
    ("guard_offenders", 0.0, True, "guard offenders don't rise"),
    ("mirror_rate", 0.02, False, "must-have mirroring falls <= 2 points"),
]
EXPAND_CHECKS = [
    ("guard_dropped", 0.0, True, "bullets dropped by the guard don't rise"),
    ("empty_entries", 0.0, True, "entries left empty don't rise"),
]

COVER_CHECKS = [
    ("factual_left", 0.0, True, "claims left unsupported after the retry don't rise"),
    ("gap_claimed", 0.0, True, "unmet must-haves named as experience don't rise"),
]
REVIEW_CHECKS = [
    ("guard_dropped_rate", 0.05, True, "suggestions dropped by the guard rise <= 5 points"),
]


def verdict(rules: list[Rule]) -> str:
    if any(r.passed is False for r in rules):
        return "FAIL"
    return "PASS" if all(r.passed for r in rules) else "INCOMPLETE"


def markdown(
    title: str, arms: dict[str, dict[str, dict]], metrics: list[str], base: str, cand: str,
    *, rules: list[Rule], model: str = "", errors: int = 0,
) -> str:
    lines = [f"# {title}", "", f"**Verdict: {verdict(rules)}**", ""]
    lines += ["| Rule | Result | Detail |", "|---|---|---|"]
    for r in rules:
        mark = {True: "pass", False: "FAIL", None: "n/a"}[r.passed]
        lines.append(f"| {r.text} | {mark} | {r.detail} |")
    lines += ["", f"## Metrics ({base} -> {cand}; control = {base} again)", "",
              "| Metric | n | base | cand | diff | 95% CI | control diff |",
              "|---|---|---|---|---|---|---|"]
    for metric in metrics:
        p = paired(arms, metric, f"{base}#0", f"{cand}#0")
        if p is None:
            continue
        c = paired(arms, metric, f"{base}#0", f"{base}#1")
        lines.append(
            f"| {metric} | {p.n} | {p.a:.3f} | {p.b:.3f} | {p.diff:+.3f} | "
            f"[{p.ci[0]:+.3f}, {p.ci[1]:+.3f}] | {f'{c.diff:+.3f}' if c else '-'} |"
        )
    lines += ["", "## Cost and speed (per case)", "",
              "| Arm | cases | p50 s | p90 s | calls | out tok | reasoning tok | est. USD |",
              "|---|---|---|---|---|---|---|---|"]
    for name in sorted(arms):
        u = usage_summary(arms[name], model)
        if not u:
            continue
        usd = f"{u['usd_per_case']:.4f}" if u["usd_per_case"] is not None else "-"
        lines.append(
            f"| {name} | {u['cases']} | {u['wall_p50_s']:.1f} | {u['wall_p90_s']:.1f} | "
            f"{u['calls']:.1f} | {u['output_tokens']:.0f} | {u['reasoning_tokens']:.0f} | {usd} |"
        )
    if errors:
        lines += ["", f"{errors} task(s) ended in error; see cases.jsonl."]
    return "\n".join(lines) + "\n"
