"""Experiments E1 (cosmetic polish on frozen drafts) and E2 (narrow anti-invention
clause): their pre-registered criteria, decisions, and the markdown summary.

Arm labels (`report.label`): `draft#0` (frozen drafts), `polish-<effort>#0` (those
drafts polished at medium / low / none), `clause#0` (fresh drafts with the clause, then
the production retry and medium polish). E1 compares `polish-medium` with `polish-none`
then `polish-low` (fixed sequence); E2 compares `polish-medium` with `clause`.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import mean

from . import report, sequential
from .sequential import Criterion

BASE = "polish-medium#0"
#: The judge reasons that cite this figure (the vnpt_b2 "45% -> 96.3%" bullet) are left
#: out of the sensitivity view: one well-known bullet should not carry a verdict.
VNPT_PATTERN = r"96\.3"
INFO_METRICS = ("fallback_rate", "guard_offenders", "over_length", "under_length",
                "verb_collisions", "phrase_collisions", "changed_rate", "mean_chars",
                "must_expressed", "unsupported_additions")


def _metric_diffs(grouped: dict, metric: str, a: str, b: str, cases: Sequence[str]) -> list:
    left, right = grouped.get(a, {}), grouped.get(b, {})
    return [right[c]["result"]["metrics"][metric] - left[c]["result"]["metrics"][metric]
            for c in cases if c in left and c in right]


def _net(verdicts: list[dict], a: str, b: str, cases: Sequence[str], exclude=None):
    scores = sequential.case_scores(verdicts, a, b, cases=cases, exclude=exclude)
    return sequential.bounds(list(scores.values()))


def e1_criteria(grouped: dict, verdicts: list[dict], cand: str,
                cases: Sequence[str]) -> list[Criterion]:
    arm = f"polish-{cand}#0"
    return [
        Criterion(f"net judge preference for {cand}", _net(verdicts, BASE, arm, cases),
                  -0.10, higher_is_better=True),
        Criterion("guard offenders per resume (change)",
                  sequential.bounds(_metric_diffs(grouped, "guard_offenders", BASE, arm, cases)),
                  0.10, higher_is_better=False),
        Criterion("over-length bullets per resume (change)",
                  sequential.bounds(_metric_diffs(grouped, "over_length", BASE, arm, cases)),
                  0.25, higher_is_better=False),
    ]


def supported_losses(base: dict, cand: dict) -> tuple[int, int]:
    """(supported must-haves the base shows and the candidate drops, ones it adds)."""
    b, c = base["result"]["must"], cand["result"]["must"]
    backed = set(b["backed"])
    lost = (set(b["shown"]) - set(c["shown"])) & backed
    gained = (set(c["shown"]) - set(b["shown"])) & backed
    return len(lost), len(gained)


def case_cost(record: dict | None, model: str) -> float | None:
    price = report._price(model)
    if record is None or price is None:
        return None
    u = record["usage"]
    return (u["input_tokens"] * price[0] + u["output_tokens"] * price[1]) / 1e6


def e2_cost_pairs(grouped: dict, cases: Sequence[str], model: str) -> list[tuple]:
    """Per case `(draft + medium polish cost, clause-arm cost)`: whole rewrite vs whole
    rewrite, every call and retry included."""
    draft, medium, clause = (grouped.get(k, {}) for k in ("draft#0", BASE, "clause#0"))
    pairs = []
    for c in cases:
        if c in draft and c in medium and c in clause:
            base = case_cost(draft[c], model)
            polish = case_cost(medium[c], model)
            pairs.append((None if base is None or polish is None else base + polish,
                          case_cost(clause[c], model)))
    return pairs


def e2_criteria(grouped: dict, verdicts: list[dict], cases: Sequence[str],
                model: str) -> list[Criterion]:
    medium, clause = grouped.get(BASE, {}), grouped.get("clause#0", {})
    common = [c for c in cases if c in medium and c in clause]
    lost = [supported_losses(medium[c], clause[c])[0] for c in common]
    return [
        Criterion("net judge preference for the clause",
                  _net(verdicts, BASE, "clause#0", cases), 0.0,
                  higher_is_better=True, strict=True),
        Criterion("supported must-haves lost per resume", sequential.bounds(lost), 0.10,
                  higher_is_better=False),
        Criterion("total model cost per resume (relative)",
                  sequential.ratio_bounds(e2_cost_pairs(grouped, cases, model)), 0.10,
                  higher_is_better=False),
    ]


def e1_missing(grouped: dict, verdicts: list[dict], cand: str,
               cases: Sequence[str]) -> list[str]:
    arm = f"polish-{cand}#0"
    return sequential.missing_cases(cases, grouped.get(BASE, {}), grouped.get(arm, {}),
                                    verdicts=verdicts, pair=(BASE, arm))


def e2_missing(grouped: dict, verdicts: list[dict], cases: Sequence[str]) -> list[str]:
    # The cost criterion needs the frozen draft too: the baseline's rewrite is two records.
    return sequential.missing_cases(
        cases, *(grouped.get(k, {}) for k in ("draft#0", BASE, "clause#0")),
        verdicts=verdicts, pair=(BASE, "clause#0"))


def e1_choice(none: str, low: str, look: int) -> str:
    """The fixed sequence: "none" first; "low" is tested only once "none" has not passed."""
    if none == "INCOMPLETE":
        return "incomplete (none): rerun the missing cases"
    if none == "PASS":
        return "ship polish none"
    if look < sequential.LOOKS and none == "CONTINUE":
        return "extend (none undecided)"
    if low == "INCOMPLETE":
        return "incomplete (low): rerun the missing cases"
    if low == "PASS":
        return "ship polish low"
    if look < sequential.LOOKS and low == "CONTINUE":
        return "extend (low undecided)"
    return "keep medium polish"


def _means(grouped: dict, cases: Sequence[str]) -> list[str]:
    arms = [a for a in ("draft#0", BASE, "polish-low#0", "polish-none#0", "clause#0")
            if a in grouped]
    rows = ["| Metric | " + " | ".join(arms) + " |", "|---" * (len(arms) + 1) + "|"]
    for metric in INFO_METRICS:
        cells = []
        for a in arms:
            vals = [grouped[a][c]["result"]["metrics"].get(metric) for c in cases
                    if c in grouped[a]]
            vals = [v for v in vals if v is not None]
            cells.append(f"{mean(vals):.3f}" if vals else "-")
        rows.append(f"| {metric} | " + " | ".join(cells) + " |")
    return rows


def _usage(grouped: dict, cases: Sequence[str], model: str) -> list[str]:
    rows = ["| Arm | cases | calls | input tok | output tok | reasoning tok | wall s | est. USD |",
            "|---|---|---|---|---|---|---|---|"]
    for a in sorted(grouped):
        recs = [grouped[a][c] for c in cases if c in grouped[a]]
        if not recs:
            continue
        u = [r["usage"] for r in recs]
        costs = [case_cost(r, model) for r in recs]
        usd = f"{mean(costs):.4f}" if all(x is not None for x in costs) else "-"
        avg = {k: mean(x[k] for x in u) for k in
               ("calls", "input_tokens", "output_tokens", "reasoning_tokens", "wall_ms")}
        rows.append(
            f"| {a} | {len(recs)} | {avg['calls']:.2f} | {avg['input_tokens']:.0f} | "
            f"{avg['output_tokens']:.0f} | {avg['reasoning_tokens']:.0f} | "
            f"{avg['wall_ms'] / 1000:.1f} | {usd} |")
    return rows


def _tally(verdicts: list[dict], a: str, b: str, cases: Sequence[str]) -> str:
    scores = sequential.case_scores(verdicts, a, b, cases=cases)
    identical = sum(1 for v in verdicts if (v.get("a"), v.get("b")) == (a, b)
                    and v.get("identical") and v["case"] in set(cases))
    vals = list(scores.values())
    return (f"{b} wins {vals.count(1)}, {a} wins {vals.count(-1)}, ties {vals.count(0)} "
            f"({identical} identical, no judge call)")


def _gap_line(gap: Sequence[str]) -> list[str]:
    if not gap:
        return []
    return [f"Missing results or verdicts for {len(gap)} case(s): {', '.join(gap)}.", ""]


def markdown(grouped: dict, verdicts: list[dict], cases: Sequence[str], look: int,
             model: str, meta: dict) -> str:
    lines = [f"# E1 polish / E2 clause — look {look} (n={len(cases)})", "",
             f"Baseline commit `{meta.get('commit', '?')}`, model {model}, "
             f"judge {meta.get('judge_model', '?')}, one-sided alpha "
             f"{sequential.ALPHA_PER_LOOK} per look.", ""]
    decisions = {}
    for cand in ("none", "low"):
        crit = e1_criteria(grouped, verdicts, cand, cases)
        gap = e1_missing(grouped, verdicts, cand, cases)
        decisions[cand] = sequential.decide(crit, look, missing=gap)
        sens = _net(verdicts, BASE, f"polish-{cand}#0", cases,
                    exclude=lambda v: sequential.cites(v, VNPT_PATTERN))
        lines += [f"## E1: polish {cand} vs medium — **{decisions[cand]}**", "",
                  *sequential.table(crit, look), "", *_gap_line(gap),
                  f"Judge: {_tally(verdicts, BASE, f'polish-{cand}#0', cases)}. "
                  f"Without vnpt_b2 citations: net {sens.estimate:+.3f} "
                  f"[{sens.lower:+.3f}, {sens.upper:+.3f}] (n={sens.n}).", ""]
    lines += [f"**E1 outcome: {e1_choice(decisions['none'], decisions['low'], look)}**", ""]
    crit = e2_criteria(grouped, verdicts, cases, model)
    gap = e2_missing(grouped, verdicts, cases)
    e2 = sequential.decide(crit, look, missing=gap)
    medium, clause = grouped.get(BASE, {}), grouped.get("clause#0", {})
    common = [c for c in cases if c in medium and c in clause]
    gained = sum(supported_losses(medium[c], clause[c])[1] for c in common)
    lost = sum(supported_losses(medium[c], clause[c])[0] for c in common)
    sens = _net(verdicts, BASE, "clause#0", cases,
                exclude=lambda v: sequential.cites(v, VNPT_PATTERN))
    lines += [f"## E2: clause vs medium — **{e2}**", "", *sequential.table(crit, look), "",
              *_gap_line(gap),
              f"Judge: {_tally(verdicts, BASE, 'clause#0', cases)}. Without vnpt_b2 "
              f"citations: net {sens.estimate:+.3f} [{sens.lower:+.3f}, {sens.upper:+.3f}]. "
              f"Supported must-haves: {lost} lost, {gained} gained over {len(common)} cases.",
              "", "## Metric means", "", *_means(grouped, cases), "",
              "## Usage per case", "", *_usage(grouped, cases, model), ""]
    return "\n".join(lines)
