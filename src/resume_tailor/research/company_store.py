"""Saved company research: app-wide, one JSON file per company. Pure, no network.

``DATA_ROOT/company_research/<slug>.json``, where the slug comes from
`identity.normalize_company`, so "Acme, Inc." and "Acme" share a file. Facts about a
company are not tied to one profile. They are never resume support either: nothing
here reaches the fabrication guard's sources, the bullets or their skills.

Research is fresh for `FRESH_DAYS`. After that the UI offers a refresh; nothing is ever
fetched again on its own. A fact the student removes stays removed (`removed` keeps its
id, which comes from its text), even when a later extraction finds it again.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.discovery import identity
from resume_tailor.infra import atomic

FRESH_DAYS = 30

SourceKind = Literal["posting", "board", "site", "news", "page", "note"]
FactKind = Literal["about", "product", "mission", "values", "size", "news"]

_LOCK = threading.Lock()


class Source(BaseModel):
    """One text the facts were read from."""

    id: str
    kind: SourceKind
    url: str | None = None
    title: str = ""
    fetched_at: str = ""
    sha: str = ""
    text: str = ""
    #: What `posting_guard` flagged in it, in plain words.
    flags: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    id: str
    text: str
    kind: FactKind
    source_id: str
    #: The source's own words that state the fact.
    excerpt: str
    #: The date its source was read.
    as_of: str = ""


class CompanyResearch(BaseModel):
    company: str
    researched_at: str = ""
    sources: list[Source] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    #: Ids of facts the student removed.
    removed: list[str] = Field(default_factory=list)
    #: Facts the guard rejected in the last extraction.
    dropped: int = 0
    #: The search service used ("brave", "tavily"), or "" when none was.
    searched_with: str = ""
    warnings: list[str] = Field(default_factory=list)
    model: str = ""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def text_id(prefix: str, *parts: str) -> str:
    """A short id that depends only on ``parts``."""
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:10]}"


def fact_id(text: str) -> str:
    return text_id("f", " ".join(text.casefold().split()))


def research_dir() -> Path:
    return config.DATA_ROOT / "company_research"


def slug(company: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "-", identity.normalize_company(company)).strip("-")
    return name[:60] or "company"


def _path(company: str) -> Path:
    return research_dir() / f"{slug(company)}.json"


def load(company: str) -> CompanyResearch | None:
    return atomic.read_cached(_path(company), CompanyResearch)


def save(research: CompanyResearch) -> None:
    path = _path(research.company)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_text(path, research.model_dump_json(indent=1) + "\n")


def remove_fact(company: str, fid: str) -> CompanyResearch | None:
    """Drop one fact and remember it; None when there is no such fact."""
    with _LOCK:
        research = load(company)
        if research is None or not any(f.id == fid for f in research.facts):
            return None
        research.facts = [f for f in research.facts if f.id != fid]
        research.removed = sorted({*research.removed, fid})
        atomic.write_text(_path(company), research.model_dump_json(indent=1) + "\n")
        return research


def is_stale(research: CompanyResearch, today: date | None = None) -> bool:
    try:
        made = datetime.fromisoformat(research.researched_at).date()
    except ValueError:
        return True
    return ((today or datetime.now(UTC).date()) - made).days > FRESH_DAYS
