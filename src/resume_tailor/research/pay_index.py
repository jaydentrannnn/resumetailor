"""Posted pay ranges across the profile's saved postings. Pure reads, no LLM.

Each application row contributes the ranges its listing's salary column and its saved
posting text state (`pay_parse.posted_ranges`), with its company, title, role family and
level, location and posting date. Parsing is cached in memory per file (path, size and
modification time), so a benchmark re-reads only postings that changed.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from resume_tailor import config
from resume_tailor.apply.funnel import store_models

from . import pay_level
from .pay_parse import PostedRange, posted_ranges


@dataclass(frozen=True)
class PostingPay:
    app_id: str
    company: str
    role: str
    family: pay_level.Family
    level: pay_level.Level
    location: str
    #: The posting date (ISO), or "" when unknown.
    on: str
    ranges: tuple[PostedRange, ...]


def _jd_path(app: store_models.Application) -> Path:
    if app.jd_text_path:
        return Path(app.jd_text_path)
    return config.APPLICATIONS_OUTPUT_DIR / app.source_job_id / "jd.txt"


@functools.lru_cache(maxsize=4096)
def _parsed(path: str, _mtime_ns: int, _size: int) -> tuple[PostedRange, ...]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    return tuple(posted_ranges(text))


def _from_file(path: Path) -> tuple[PostedRange, ...]:
    try:
        stat = path.stat()
    except OSError:
        return ()
    return _parsed(str(path), stat.st_mtime_ns, stat.st_size)


def ranges_for(app: store_models.Application) -> tuple[PostedRange, ...]:
    """What ``app``'s listing and saved posting state, listing first, each range once."""
    found = [*posted_ranges(app.salary or ""), *_from_file(_jd_path(app))]
    unique: dict[tuple[float, float, str, str], PostedRange] = {}
    for item in found:
        unique.setdefault((item.low, item.high, item.currency, item.period), item)
    return tuple(unique.values())


def posting_pay(app: store_models.Application) -> PostingPay:
    on, _known = store_models.posted_date(app)
    return PostingPay(
        app_id=app.source_job_id, company=app.company, role=app.role,
        family=pay_level.family(app.role), level=pay_level.level(app.role),
        location=app.location, on=on, ranges=ranges_for(app),
    )


def postings(apps: list[store_models.Application]) -> list[PostingPay]:
    """Every row that states pay, one entry per row."""
    return [entry for entry in map(posting_pay, apps) if entry.ranges]
