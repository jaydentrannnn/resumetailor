"""Experiment E's report: current vs hybrid extraction, by posting group.

Arm labels: `current#0`, `hybrid#0`, their reruns `current#1` / `hybrid#1` (run-to-run
agreement), and `<method>@<tag>#0` for the same methods on a second model
(cross-model agreement, the original argument for a dictionary).
"""

from __future__ import annotations

from statistics import mean

from . import metrics
from .report import Rule, by_arm, judge_tally, loss_rate, usage_summary, verdict

GROUPS = ("tech", "finance", "nontech")
HARD = ("short", "hedged", "short_names")


def _rate(record: dict) -> float:
    m = record["result"]["metrics"]
    return m["must_shown"] / m["must_total"] if m["must_total"] else 1.0


def _keywords(record: dict, *, must_only: bool = False) -> set[str]:
    return {k["canonical"] for k in record["result"]["requirements"]["keywords"]
            if not must_only or k["importance"] == "must_have"}


def agreement(grouped: dict, a: str, b: str, *, must_only: bool = False) -> tuple[float, int]:
    """Mean keyword-set F1 between two arms over the cases both completed."""
    common = set(grouped.get(a, {})) & set(grouped.get(b, {}))
    scores = [metrics.f1(_keywords(grouped[a][c], must_only=must_only),
                         _keywords(grouped[b][c], must_only=must_only)) for c in common]
    return (mean(scores) if scores else float("nan"), len(scores))


def _no_signal(*records: dict) -> bool:
    """Neither arm's selection matched any keyword: the resume has nothing to show for
    this posting (an empty profile, or a nurse posting against a software resume), so
    its coverage says nothing about the extraction."""
    return all(r["result"]["metrics"]["keywords_shown"] == 0 for r in records)


def _coverage_diff(grouped: dict, a: str, b: str, cases: set[str]) -> tuple[float, int]:
    common = {c for c in set(grouped.get(a, {})) & set(grouped.get(b, {})) & cases
              if not _no_signal(grouped[a][c], grouped[b][c])}
    diffs = [_rate(grouped[b][c]) - _rate(grouped[a][c]) for c in common]
    return (mean(diffs) if diffs else float("nan"), len(diffs))


def _cases(records: list[dict], *, group: str | None = None, tag: str | None = None) -> set:
    return {r["case"] for r in records
            if (group is None or r.get("group") == group)
            and (tag is None or tag in r.get("tags", []))}


def rules(records: list[dict], verdicts: list[dict], tag: str | None) -> list[Rule]:
    grouped = by_arm(records)
    out = []
    tech = _cases(records, group="tech")
    other = _cases(records) - tech
    slack = abs(_coverage_diff(grouped, "current#0", "current#1", tech | other)[0] or 0.0)
    slack = 0.0 if slack != slack else slack  # NaN: no control
    d, n = _coverage_diff(grouped, "current#0", "hybrid#0", tech)
    out.append(Rule("tech: must-have coverage drops <= 1 point", None if n == 0 else
                    d >= -0.01 - slack, f"diff {d:+.3f} (n={n}, control drift {slack:.3f})"))
    d, n = _coverage_diff(grouped, "current#0", "hybrid#0", other)
    out.append(Rule("non-tech: must-have coverage improves", None if n == 0 else d > slack,
                    f"diff {d:+.3f} (n={n})"))
    cand = loss_rate(judge_tally(verdicts, "current#0", "hybrid#0"))
    noise = loss_rate(judge_tally(verdicts, "current#0", "current#1"))
    out.append(Rule(
        "judge: hybrid loses no more often than current vs itself",
        None if cand is None or noise is None else cand <= noise,
        "judge not run" if cand is None or noise is None
        else f"hybrid lost {cand:.0%}, control lost {noise:.0%}"))
    if tag:
        cur, n1 = agreement(grouped, "current#0", f"current@{tag}#0")
        hyb, n2 = agreement(grouped, "hybrid#0", f"hybrid@{tag}#0")
        ok = None if min(n1, n2) == 0 else hyb - cur >= 0.10
        out.append(Rule(f"cross-model ({tag}) keyword F1 improves >= 0.10", ok,
                        f"current {cur:.3f} (n={n1}) -> hybrid {hyb:.3f} (n={n2})"))
    else:
        out.append(Rule("cross-model keyword F1 improves >= 0.10", None, "second model not run"))
    cu, hy = usage_summary(grouped.get("current#0", {})), usage_summary(grouped.get("hybrid#0", {}))
    if cu and hy:
        ok = (hy["wall_p50_s"] <= 1.1 * cu["wall_p50_s"]
              and hy["output_tokens"] <= 1.1 * cu["output_tokens"])
        out.append(Rule("latency and output tokens not worse (+10%)", ok,
                        f"p50 {cu['wall_p50_s']:.1f}s -> {hy['wall_p50_s']:.1f}s, out tokens "
                        f"{cu['output_tokens']:.0f} -> {hy['output_tokens']:.0f}"))
    return out


def _row(grouped: dict, arm: str, cases: set[str]) -> str:
    recs = [grouped.get(arm, {})[c] for c in cases if c in grouped.get(arm, {})]
    if not recs:
        return f"| {arm} | 0 | - | - | - | - |"
    m = [r["result"]["metrics"] for r in recs]
    return (f"| {arm} | {len(recs)} | {mean(_rate(r) for r in recs):.3f} | "
            f"{mean(x['keywords'] for x in m):.1f} | {mean(x['must_haves'] for x in m):.1f} | "
            f"{mean(x['verbatim_violations'] for x in m):.2f} |")


def markdown(records: list[dict], verdicts: list[dict], tag: str | None) -> str:
    grouped = by_arm(records)
    result = rules(records, verdicts, tag)
    lines = ["# extract: current vs hybrid (E)", "", f"**Verdict: {verdict(result)}**", "",
             "| Rule | Result | Detail |", "|---|---|---|"]
    for r in result:
        lines.append(f"| {r.text} | {({True: 'pass', False: 'FAIL', None: 'n/a'})[r.passed]} "
                     f"| {r.detail} |")
    header = ["| Arm | n | must-have coverage | keywords | must-haves | verbatim violations |",
              "|---|---|---|---|---|---|"]
    slices = [(g, _cases(records, group=g)) for g in GROUPS]
    slices += [(f"hard: {t}", _cases(records, tag=t)) for t in HARD]
    for name, cases in slices:
        if not cases:
            continue
        lines += ["", f"## {name}", "", *header]
        lines += [_row(grouped, arm, cases) for arm in sorted(grouped)]
    lines += ["", "## Agreement (keyword F1; must-have F1)", "", "| Pair | all | must | n |",
              "|---|---|---|---|"]
    pairs = [("current#0", "current#1"), ("hybrid#0", "hybrid#1"), ("current#0", "hybrid#0")]
    if tag:
        pairs += [("current#0", f"current@{tag}#0"), ("hybrid#0", f"hybrid@{tag}#0")]
    for a, b in pairs:
        f_all, n = agreement(grouped, a, b)
        f_must, _ = agreement(grouped, a, b, must_only=True)
        if n:
            lines.append(f"| {a} vs {b} | {f_all:.3f} | {f_must:.3f} | {n} |")
    lines += ["", "## Cost and speed (per case)", "",
              "| Arm | cases | p50 s | out tok | reasoning tok |", "|---|---|---|---|---|"]
    for arm in sorted(grouped):
        u = usage_summary(grouped[arm])
        lines.append(f"| {arm} | {u['cases']} | {u['wall_p50_s']:.1f} | "
                     f"{u['output_tokens']:.0f} | {u['reasoning_tokens']:.0f} |")
    errors = sum(1 for r in records if r.get("status") == "error")
    if errors:
        lines += ["", f"{errors} task(s) ended in error; see cases.jsonl."]
    return "\n".join(lines) + "\n"
