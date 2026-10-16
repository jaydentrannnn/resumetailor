"""Two-look sequential decisions on case-level bootstrap bounds (experiments E1, E2).

The unit is the posting case: a judge verdict that combines both orders is one
observation, and every bootstrap resamples whole cases. Each look compares a one-sided
bound with a pre-registered bar:

* PASS: the bound on the good side clears the bar.
* FUTILE: the bound on the bad side misses it, so even the optimistic reading fails.
  (Non-binding: stopping early for futility never inflates the false-pass rate.)
* CONTINUE: neither, at look 1; extend the sample once.
* FAIL: anything but PASS at the last look. Failing means "not shown", not "worse".
* INCOMPLETE: a declared case lacks a result in either arm or a judge verdict. Never
  decided on the cases that happened to finish: a gap is rerun, not dropped.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from statistics import mean

#: Pocock boundary for two equally spaced looks at an overall one-sided alpha of 0.05:
#: nominal one-sided alpha 0.0304 per look (z = 1.875), i.e. a ~97% one-sided bound.
ALPHA_PER_LOOK = 0.0304
LOOKS = 2
RESAMPLES = 4000
#: Below this many cases the bootstrap is too coarse to decide anything (smoke runs).
MIN_CASES = 20


@dataclass(frozen=True)
class Bound:
    estimate: float
    lower: float
    upper: float
    n: int


def _percentiles(stats: list[float], alpha: float) -> tuple[float, float]:
    stats = sorted(stats)
    k = len(stats)
    return stats[int(alpha * k)], stats[min(k - 1, int((1 - alpha) * k))]


def bounds(values: Sequence[float], *, alpha: float = ALPHA_PER_LOOK,
           resamples: int = RESAMPLES, seed: int = 0) -> Bound:
    """One-sided lower and upper percentile-bootstrap bounds on the mean of `values`
    (one value per case)."""
    values = list(values)
    if len(values) < 2:
        nan = float("nan")
        return Bound(mean(values) if values else nan, nan, nan, len(values))
    rng = random.Random(seed)
    stats = [mean(rng.choices(values, k=len(values))) for _ in range(resamples)]
    return Bound(mean(values), *_percentiles(stats, alpha), len(values))


def ratio_bounds(pairs: Sequence[tuple[float, float]], *, alpha: float = ALPHA_PER_LOOK,
                 resamples: int = RESAMPLES, seed: int = 0) -> Bound:
    """Bounds on `sum(b) / sum(a) - 1` over `(a, b)` per-case pairs (relative cost)."""
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]

    def ratio(sample: Sequence[tuple[float, float]]) -> float:
        base = sum(a for a, _ in sample)
        return sum(b for _, b in sample) / base - 1 if base else float("nan")

    if len(pairs) < 2:
        nan = float("nan")
        return Bound(ratio(pairs) if pairs else nan, nan, nan, len(pairs))
    rng = random.Random(seed)
    stats = [ratio(rng.choices(pairs, k=len(pairs))) for _ in range(resamples)]
    return Bound(ratio(pairs), *_percentiles(stats, alpha), len(pairs))


# -- judge -----------------------------------------------------------------------------


def cites(verdict: dict, pattern: str) -> bool:
    """Whether either order's reason matches `pattern` (case-insensitive regex)."""
    return any(re.search(pattern, r or "", re.IGNORECASE) for r in verdict.get("reasons", []))


def case_scores(verdicts: Iterable[dict], a: str, b: str, *, cases: Iterable[str] | None = None,
                exclude: Callable[[dict], bool] | None = None) -> dict[str, int]:
    """`{case: +1 if b won, -1 if a won, 0 tie}` for the pair (a, b); errors are skipped
    and the last verdict for a case wins. The mean is the net preference for `b`."""
    wanted = set(cases) if cases is not None else None
    out: dict[str, int] = {}
    for v in verdicts:
        if (v.get("a"), v.get("b")) != (a, b) or v.get("winner") not in {"a", "b", "tie"}:
            continue
        if wanted is not None and v["case"] not in wanted:
            continue
        if exclude is not None and exclude(v):
            out.pop(v["case"], None)
            continue
        out[v["case"]] = {"a": -1, "b": 1, "tie": 0}[v["winner"]]
    return out


# -- decisions -------------------------------------------------------------------------


@dataclass(frozen=True)
class Criterion:
    """`bound` must clear `bar`: from above when `higher_is_better`, else from below."""

    name: str
    bound: Bound
    bar: float
    higher_is_better: bool
    strict: bool = False

    def _clears(self, value: float) -> bool:
        if value != value:  # NaN: too few cases to decide
            return False
        if self.higher_is_better:
            return value > self.bar if self.strict else value >= self.bar
        return value < self.bar if self.strict else value <= self.bar

    def decision(self, look: int) -> str:
        if self.bound.n < MIN_CASES:
            return "FAIL" if look >= LOOKS else "CONTINUE"
        good, bad = ((self.bound.lower, self.bound.upper) if self.higher_is_better
                     else (self.bound.upper, self.bound.lower))
        if self._clears(good):
            return "PASS"
        if look >= LOOKS:
            return "FAIL"
        if bad == bad and not self._clears(bad):
            return "FUTILE"
        return "CONTINUE"


def missing_cases(cases: Sequence[str], *arms: dict, verdicts: Iterable[dict] = (),
                  pair: tuple[str, str] | None = None) -> list[str]:
    """Declared `cases` without an ok record in every arm (`{case: record}` maps) or,
    with `pair`, without a judge verdict for that (a, b) pair."""
    judged = {v["case"] for v in verdicts
              if pair is not None and (v.get("a"), v.get("b")) == pair
              and v.get("winner") in {"a", "b", "tie"}}
    return [c for c in cases
            if any(c not in arm for arm in arms) or (pair is not None and c not in judged)]


def decide(criteria: Sequence[Criterion], look: int, *, missing: Sequence[str] = ()) -> str:
    """PASS only when every criterion passes; FUTILE as soon as one is futile;
    INCOMPLETE whenever a declared case is missing."""
    if missing:
        return "INCOMPLETE"
    decisions = [c.decision(look) for c in criteria]
    if all(d == "PASS" for d in decisions):
        return "PASS"
    if look >= LOOKS:
        return "FAIL"
    return "FUTILE" if "FUTILE" in decisions else "CONTINUE"


def table(criteria: Sequence[Criterion], look: int) -> list[str]:
    """Markdown rows: criterion, estimate, one-sided bounds, bar, decision."""
    rows = ["| Criterion | n | estimate | lower | upper | bar | decision |",
            "|---|---|---|---|---|---|---|"]
    for c in criteria:
        side = (">" if c.strict else ">=") if c.higher_is_better else ("<" if c.strict else "<=")
        b = c.bound
        rows.append(f"| {c.name} | {b.n} | {b.estimate:+.3f} | {b.lower:+.3f} | "
                    f"{b.upper:+.3f} | {side} {c.bar:+.3f} | {c.decision(look)} |")
    return rows
