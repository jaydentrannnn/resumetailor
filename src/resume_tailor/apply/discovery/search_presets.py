"""Predefined keyword-search choices: position x level x industry (no network, no LLM).

Adzuna and USAJobs take only keyword phrases, a place and a recency window, so a preset
is just a way to fill those fields (`SourceConfig.query`, `include`, `exclude`) from a
short vocabulary. Level is therefore a *title heuristic*, not a search parameter: the
real seniority gate stays `screen.allowed_seniority` after JD extraction.

Rules baked into the data:
- `include` words match at a word start (`source_watchlists._keyword_re`), so every word
  here is chosen not to begin an unrelated title ("intern" is special-cased there so it
  never matches "Internal Audit").
- A new-grad search has no `include`: the entry-level finance titles ("Investment
  Banking Analyst", "Audit Associate") carry no level word, so requiring one would drop
  them. It only skips obviously senior titles.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Most phrases one search holds (mirrors the SPA's `MAX_PHRASES` and `job_apis`).
MAX_PHRASES = 5

#: Titles no early-career search should keep. "manager" and "lead" are left out on
#: purpose: they open real entry roles ("Product Manager Intern", "Leadership Program").
SENIOR_WORDS = (
    "senior", "sr", "principal", "director", "vice president", "vp", "managing director",
    "head of", "chief",
)


@dataclass(frozen=True)
class Position:
    id: str
    label: str
    #: Base title phrases, strongest first; a level wraps each one ("{} intern").
    phrases: tuple[str, ...]


@dataclass(frozen=True)
class Level:
    id: str
    label: str
    #: How a base phrase becomes a search phrase at this level.
    phrase: str
    #: Title words a result must contain (empty keeps every non-senior title).
    include: tuple[str, ...]


@dataclass(frozen=True)
class Industry:
    id: str
    label: str
    positions: tuple[str, ...]


POSITIONS: tuple[Position, ...] = (
    Position("investment-banking", "Investment banking",
             ("investment banking analyst", "m&a analyst", "capital markets analyst")),
    Position("markets", "Sales, trading & research",
             ("sales and trading analyst", "markets analyst", "equity research analyst")),
    Position("asset-management", "Asset & wealth management",
             ("investment analyst", "portfolio analyst", "wealth management analyst")),
    Position("financial-analyst", "Financial analyst",
             ("financial analyst", "finance analyst", "corporate finance analyst")),
    Position("fpa", "FP&A & treasury",
             ("fp&a analyst", "treasury analyst", "financial planning analyst")),
    Position("accounting-audit", "Accounting & audit",
             ("audit associate", "accounting analyst", "staff accountant", "tax associate")),
    Position("risk-compliance", "Risk & credit",
             ("risk analyst", "credit analyst", "compliance analyst")),
    Position("strategy-consulting", "Strategy consulting",
             ("strategy consultant", "management consulting analyst", "business analyst")),
    Position("tech-consulting", "Technology consulting",
             ("technology consultant", "digital consultant", "systems analyst")),
    Position("business-analyst", "Business & data analyst",
             ("business analyst", "data analyst", "operations analyst")),
)

LEVELS: tuple[Level, ...] = (
    Level("intern", "Internship", "{} intern", ("intern", "summer analyst", "summer associate")),
    Level("new_grad", "New grad / entry level", "entry level {}", ()),
    Level(
        "off_cycle", "Off-cycle / co-op", "{} co-op", ("co-op", "coop", "off-cycle", "off cycle")
    ),
    Level("program", "Rotational / early-career program", "{} program",
          ("rotational", "rotation", "analyst program", "development program", "early career")),
)

INDUSTRIES: tuple[Industry, ...] = (
    Industry("banking", "Banking & capital markets",
             ("investment-banking", "markets", "risk-compliance")),
    Industry("asset-management", "Asset & wealth management",
             ("asset-management", "markets", "financial-analyst")),
    Industry("corporate-finance", "Corporate finance",
             ("financial-analyst", "fpa", "accounting-audit")),
    Industry("accounting", "Accounting, audit & tax", ("accounting-audit", "risk-compliance")),
    Industry("consulting", "Consulting",
             ("strategy-consulting", "tech-consulting", "business-analyst")),
    Industry("fintech", "Fintech & payments",
             ("financial-analyst", "risk-compliance", "business-analyst")),
)

_POSITIONS = {p.id: p for p in POSITIONS}
_LEVELS = {lv.id: lv for lv in LEVELS}


@dataclass(frozen=True)
class SearchPreset:
    """The `SourceConfig` fields a preset fills."""

    query: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]


def build_search(positions: list[str], level: str) -> SearchPreset:
    """The query phrases and title filters for ``positions`` at ``level``.

    Phrases are taken round-robin (every position's first phrase, then every second
    one), so five phrases always cover as many positions as were chosen.

    Raises:
        ValueError: an unknown position or level, or no positions.
    """
    if level not in _LEVELS:
        raise ValueError(f"unknown level {level!r}")
    if not positions:
        raise ValueError("choose at least one position")
    unknown = [p for p in positions if p not in _POSITIONS]
    if unknown:
        raise ValueError(f"unknown position {unknown[0]!r}")
    chosen = [_POSITIONS[p] for p in dict.fromkeys(positions)]
    lv = _LEVELS[level]
    phrases: list[str] = []
    depth = max(len(p.phrases) for p in chosen)
    for rank in range(depth):
        for position in chosen:
            if rank < len(position.phrases) and len(phrases) < MAX_PHRASES:
                phrases.append(lv.phrase.format(position.phrases[rank]))
    # The comma is the phrase separator in `SourceConfig.query`, so none may contain one.
    return SearchPreset(", ".join(phrases), lv.include, SENIOR_WORDS)
