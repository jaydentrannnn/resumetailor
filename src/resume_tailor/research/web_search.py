"""Web search for company research: Brave or Tavily, with the student's own key.

Brave (`BRAVE_SEARCH_API_KEY`) is used when both keys are saved; with neither, search is
skipped and research reads only the posting and the pages the student adds. Queries carry
the company name and nothing else (`company_queries`). A hit is a lead, never a source:
only a page fetched through `polite_fetch` becomes one. Keys are read with
`config.credential` and never logged or put in an error message.

These are API calls with a key, not page reads, so they go straight through httpx rather
than the robots-checking fetcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from resume_tailor import config

Provider = Literal["brave", "tavily"]
KEYS: dict[Provider, str] = {"brave": "BRAVE_SEARCH_API_KEY", "tavily": "TAVILY_API_KEY"}
TIMEOUT = 15.0
_BRAVE = "https://api.search.brave.com/res/v1/web/search"
_TAVILY = "https://api.tavily.com/search"


class SearchError(Exception):
    """A search that failed; the message never contains the key."""


@dataclass(frozen=True)
class Hit:
    title: str
    url: str
    snippet: str


def provider() -> Provider | None:
    """The search service a saved key allows, Brave first."""
    for name, key in KEYS.items():
        if config.credential(key):
            return name
    return None


def company_queries(company: str) -> list[str]:
    """The searches for one company: its name, quoted, and nothing about the student."""
    name = " ".join(company.replace('"', " ").split())
    return [f'"{name}" official site', f'"{name}" news'] if name else []


def _brave(query: str, n: int, key: str) -> list[Hit]:
    response = httpx.get(
        _BRAVE, params={"q": query, "count": n}, timeout=TIMEOUT,
        headers={"Accept": "application/json", "X-Subscription-Token": key},
    )
    response.raise_for_status()
    results = ((response.json().get("web") or {}).get("results")) or []
    return [Hit(str(r.get("title") or ""), str(r.get("url") or ""),
                str(r.get("description") or "")) for r in results if isinstance(r, dict)]


def _tavily(query: str, n: int, key: str) -> list[Hit]:
    response = httpx.post(
        _TAVILY, json={"query": query, "max_results": n, "search_depth": "basic"},
        timeout=TIMEOUT, headers={"Authorization": f"Bearer {key}"},
    )
    response.raise_for_status()
    results: list[Any] = response.json().get("results") or []
    return [Hit(str(r.get("title") or ""), str(r.get("url") or ""),
                str(r.get("content") or "")) for r in results if isinstance(r, dict)]


def search(query: str, n: int = 5) -> list[Hit]:
    """Up to ``n`` hits for ``query``; none when no key is saved."""
    name = provider()
    if name is None:
        return []
    key = config.credential(KEYS[name])
    label = name.capitalize()
    try:
        hits = (_brave if name == "brave" else _tavily)(query, n, key)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        reason = "rejected the key" if status in (401, 403) else f"answered {status}"
        raise SearchError(f"{label} search {reason}.") from None
    except (httpx.HTTPError, ValueError, AttributeError):
        raise SearchError(f"{label} search could not be reached.") from None
    return [h for h in hits if h.url.startswith(("https://", "http://"))][:n]
