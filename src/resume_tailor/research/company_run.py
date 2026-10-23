"""Research one company: read its sources, keep the guarded facts, save. Started by hand.

A first research, or a refresh, reads every automatic source again (posting, board,
official site, news) plus the pages and notes the student added before, which keep
their place. Adding a page or note reads only that and keeps everything read before.
Facts are then extracted from all sources (cached per source set), so a fact the
student removed stays removed. Nothing runs on a schedule.
"""

from __future__ import annotations

from collections.abc import Sequence

from resume_tailor.infra.polite_fetch import Fetcher
from resume_tailor.pipeline import company_research

from . import company_sources, company_store
from .company_store import CompanyResearch, Source

#: The most source text one extraction sends, so a small local model's context holds it.
PROMPT_CHARS = 36_000


class NothingToRead(Exception):
    """No source had any text."""


def _within_budget(sources: list[Source], warnings: list[str]) -> list[Source]:
    kept: list[Source] = []
    used = 0
    for source in sources:
        if used + len(source.text) > PROMPT_CHARS:
            continue
        kept.append(source)
        used += len(source.text)
    if left := len(sources) - len(kept):
        warnings.append(f"{left} longer page{'s' if left > 1 else ''} left out to keep the "
                        "request short.")
    return kept


def run(
    *, company: str, jd_text: str = "", canonical_key: str = "", site_url: str = "",
    urls: Sequence[str] = (), notes: Sequence[str] = (), refresh: bool = False,
    fetcher: Fetcher | None = None,
) -> CompanyResearch:
    """Research ``company`` and save the result. Raises `NothingToRead` or RuntimeError."""
    previous = company_store.load(company)
    own_fetcher = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        if previous is None or refresh:
            auto = company_sources.automatic(
                company=company, jd_text=jd_text, canonical_key=canonical_key,
                fetcher=fetcher, site_url=site_url,
            )
            before = [s for s in previous.sources if s.kind in ("page", "note")] if previous else []
            again = company_sources.added(
                urls=[s.url for s in before if s.kind == "page" and s.url],
                notes=[s.text for s in before if s.kind == "note"], fetcher=fetcher,
            )
            sources, warnings = auto.sources + again.sources, auto.warnings + again.warnings
            searched = auto.searched_with
        else:
            sources, warnings = list(previous.sources), []
            searched = previous.searched_with
        new = company_sources.added(urls=urls, notes=notes, fetcher=fetcher)
    finally:
        if own_fetcher:
            fetcher.close()
    sources = list({s.id: s for s in sources + new.sources}.values())
    warnings += new.warnings
    if not sources:
        raise NothingToRead(f"Nothing to read about {company}: add a page or a note.")
    sent = _within_budget(sources, warnings)
    removed = previous.removed if previous else []
    found = company_research.extract(company, sent, removed=removed)
    research = CompanyResearch(
        company=previous.company if previous else company, researched_at=company_store.now(),
        sources=sources, facts=found.facts, removed=removed, dropped=found.dropped,
        searched_with=searched, warnings=warnings, model=found.model,
    )
    if previous and not refresh:
        research.researched_at = previous.researched_at or research.researched_at
    company_store.save(research)
    return research
