"""Posted pay ranges for roles like one application's. Pure, no LLM.

At most three groups: the same company (any role), the same role family and level in
this posting's state (or its city, when it names no state), and the same family and
level anywhere. Every group is split by currency and pay period, which are never
converted or mixed (an hourly internship and a yearly salary are different numbers, not
one scale). A split with at least
`QUANTILE_MIN` figures gets its 25th, 50th and 75th percentile; a smaller one lists each
figure. Each figure counts as its range's midpoint, or an imported row's median.

This describes what postings and imported data say, never what the student will be
offered, and it is never resume support.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from resume_tailor.apply.discovery import identity

from . import pay_level
from .pay_import import Dataset
from .pay_index import PostingPay
from .pay_parse import Currency, Period

#: Figures needed before percentiles are shown instead of the figures themselves.
QUANTILE_MIN = 5
#: Individual figures listed when a split is too small for percentiles.
LISTED = 8

GroupKind = Literal["company", "near", "anywhere"]
_STATE = re.compile(r",\s*([A-Z]{2})\b")


@dataclass(frozen=True)
class Figure:
    """One posted range or imported row, as the benchmark shows it."""

    low: float
    high: float
    company: str
    role: str
    location: str
    on: str
    #: "Saved posting" or the dataset's name.
    source: str
    excerpt: str = ""
    app_id: str = ""
    sample_size: int | None = None
    family: pay_level.Family = "other"
    level: pay_level.Level = "mid"
    currency: Currency = "USD"
    period: Period = "year"
    #: An imported row's stated median, which beats the range's midpoint.
    median: float | None = None

    @property
    def point(self) -> float:
        return self.median if self.median is not None else (self.low + self.high) / 2


@dataclass
class Split:
    currency: Currency
    period: Period
    n: int
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    #: The figures themselves when ``n`` is below `QUANTILE_MIN` (up to `LISTED`).
    figures: list[Figure] = field(default_factory=list)


@dataclass
class Group:
    kind: GroupKind
    label: str
    n: int
    sources: list[str]
    first_on: str
    last_on: str
    splits: list[Split]


def figures_from_postings(postings: list[PostingPay]) -> list[Figure]:
    return [
        Figure(r.low, r.high, p.company, p.role, p.location, p.on, "Saved posting",
               r.excerpt, p.app_id, None, p.family, p.level, r.currency, r.period)
        for p in postings for r in p.ranges
    ]


def figures_from_datasets(datasets: list[Dataset]) -> list[Figure]:
    found: list[Figure] = []
    for dataset in datasets:
        for row in dataset.rows:
            if row.low is not None and row.high is not None:
                low, high = row.low, row.high
            elif row.median is not None:
                low = high = row.median
            else:
                continue
            found.append(Figure(
                low, high, row.company, row.role, row.location,
                row.as_of or dataset.as_of or dataset.imported_at[:10],
                dataset.name + (f" ({row.source})" if row.source else ""),
                sample_size=row.sample_size, family=pay_level.family(row.role),
                level=pay_level.level(row.level or row.role), currency=row.currency,
                period=row.period, median=row.median,
            ))
    return found


def _places(location: str) -> tuple[set[str], set[str]]:
    """The state codes and city names a location names ("Austin, TX | Remote")."""
    states: set[str] = set()
    cities: set[str] = set()
    for part in re.split(r"\s*(?:\||;|/|\n)\s*", location or ""):
        states.update(_STATE.findall(part))
        city = part.split(",")[0].strip()
        if city and city.casefold() not in ("remote", "hybrid", "united states", "usa", "us"):
            cities.add(city.casefold())
    return states, cities


def _near(location: str) -> tuple[str, Callable[[str], bool]]:
    """Where "near" means for ``location`` (its states, else its cities) and a test."""
    states, cities = _places(location)
    if states:
        return " or ".join(sorted(states)), lambda other: bool(states & _places(other)[0])
    if cities:
        return location, lambda other: bool(cities & _places(other)[1])
    return "", lambda _other: False


def _split(figures: list[Figure]) -> list[Split]:
    by: dict[tuple[str, str], list[Figure]] = {}
    for figure in figures:
        by.setdefault((figure.currency, figure.period), []).append(figure)
    splits: list[Split] = []
    for (currency, period), items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        split = Split(currency, period, len(items))  # type: ignore[arg-type]
        if len(items) >= QUANTILE_MIN:
            q1, q2, q3 = statistics.quantiles([f.point for f in items], n=4, method="inclusive")
            split.p25, split.median, split.p75 = q1, q2, q3
        else:
            split.figures = sorted(items, key=lambda f: f.point)[:LISTED]
        splits.append(split)
    return splits


def _group(kind: GroupKind, label: str, figures: list[Figure]) -> Group | None:
    if not figures:
        return None
    dates = sorted(f.on for f in figures if f.on)
    return Group(
        kind=kind, label=label, n=len(figures),
        sources=sorted({f.source for f in figures}),
        first_on=dates[0] if dates else "", last_on=dates[-1] if dates else "",
        splits=_split(figures),
    )


def benchmark(
    *, company: str, role: str, location: str, figures: list[Figure], exclude_app_id: str = ""
) -> list[Group]:
    """Up to three groups of figures like ``role`` at ``company`` in ``location``."""
    others = [f for f in figures if not (exclude_app_id and f.app_id == exclude_app_id)]
    family, level = pay_level.family(role), pay_level.level(role)
    same_company = identity.normalize_company(company)
    place, is_near = _near(location)
    alike = [f for f in others if (f.family, f.level) == (family, level)]
    title = f"{pay_level.LEVEL_LABELS[level]}, {pay_level.FAMILY_LABELS[family].lower()}"
    groups = [
        _group("company", f"Other roles at {company}", [
            f for f in others
            if same_company and identity.normalize_company(f.company) == same_company
        ]),
        _group("near", f"{title}, in {place}" if place else "", [
            f for f in alike if is_near(f.location)
        ]),
        _group("anywhere", f"{title}, anywhere", alike),
    ]
    return [g for g in groups if g is not None and g.label]
