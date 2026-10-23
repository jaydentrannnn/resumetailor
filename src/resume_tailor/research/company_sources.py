"""Where company research reads from, in order. Every fetch goes through `polite_fetch`.

1. The saved posting's "about us" part (nothing fetched).
2. The Greenhouse board's company blurb, for a Greenhouse posting.
3. The official site: a page the student gives, else a search hit whose domain matches
   the company's name. Its homepage is read, plus the given page or the first of
   /about, /about-us and /company that answers.
4. Up to three news pages from a news search, on other domains.
5. Pages and notes the student adds.

Search hits are leads: their snippets are never a source. Links inside a posting are
never followed. Every text is guarded and capped by `pages.py`.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import httpx

from resume_tailor.apply.discovery import identity
from resume_tailor.infra.polite_fetch import Fetched, Fetcher, FetchError
from resume_tailor.pipeline import posting_guard

from . import pages, web_search
from .company_store import Source, SourceKind, now, text_id

MAX_NEWS = 3
_ABOUT_PATHS = ("/about", "/about-us", "/company")
#: Hosts that write about companies but are not the company's own site.
_NOT_OFFICIAL = (
    "linkedin.", "glassdoor.", "indeed.", "wikipedia.", "crunchbase.", "bloomberg.",
    "facebook.", "twitter.", "x.com", "youtube.", "instagram.", "reddit.", "tiktok.",
    "greenhouse.io", "lever.co", "ashbyhq.", "myworkdayjobs.", "smartrecruiters.",
    "builtin", "zoominfo.", "levels.fyi", "simplify.jobs", "github.com", "medium.com",
    "wellfound.", "handshake",
)
_NOT_NEWS = ("linkedin.", "glassdoor.", "indeed.", "facebook.", "twitter.", "x.com",
             "youtube.", "instagram.", "reddit.", "tiktok.")
_NAME_FILLER = {"the", "company", "group", "holdings", "technologies", "technology", "labs"}
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}
#: Words a company adds to its name to get a domain: acmehq.com, acmeinc.com.
_DOMAIN_ENDINGS = ("hq", "inc", "corp", "app", "ai", "io", "tech", "labs", "group", "usa")

_ABOUT_HEADING = re.compile(
    r"^(about\b(?!\s+(?:the|this)\s+(?:role|job|position|opportunity|internship)\b)"
    r"(?!\s+you\b)|who we are|our (?:mission|story|company|values)|"
    r"company (?:overview|description|profile)|life at\b)", re.IGNORECASE,
)
_JOB_HEADING = re.compile(
    r"^(about (?:the|this) (?:role|job|position|opportunity|internship)|the role|"
    r"(?:your |the )?responsibilities|what you(?:'|’)ll|what we(?:'|’)re looking|"
    r"requirements|(?:basic |minimum |preferred )?qualifications|who you are|"
    r"your role|job description|you will|benefits|compensation|the opportunity|"
    r"position (?:summary|overview)|duties)", re.IGNORECASE,
)
_ABOUT_MAX = 3000
_POSTING_MAX = 6000


@dataclass
class Gathered:
    sources: list[Source] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    searched_with: str = ""


def _source(kind: SourceKind, text: str, *, url: str | None = None, title: str = "",
            findings: posting_guard.GuardFindings | None = None) -> Source:
    return Source(
        id=text_id("s", kind, url or text), kind=kind, url=url, title=title,
        fetched_at=now(), sha=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        text=text, flags=posting_guard.warnings(findings),
    )


def about_section(jd_text: str) -> str:
    """The posting's "About us" part, or "" when it has no such heading."""
    lines = [line.strip() for line in jd_text.splitlines()]
    for start, line in enumerate(lines):
        heading = line.rstrip(":").strip("#* ")
        if len(heading) <= 60 and _ABOUT_HEADING.match(heading):
            kept: list[str] = []
            for nxt in lines[start + 1:]:
                if _JOB_HEADING.match(nxt.strip("#* ")) and len(nxt) <= 60:
                    break
                if nxt:
                    kept.append(nxt)
            body = "\n".join(kept).strip()
            if body:
                return f"{heading}\n{body}"[:_ABOUT_MAX]
    return ""


def posting_source(jd_text: str) -> Source | None:
    about = about_section(jd_text)
    text, findings = pages.clean(about or jd_text[:_POSTING_MAX])
    return _source("posting", text, title="Job posting", findings=findings) if text else None


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host
    except (httpx.InvalidURL, TypeError):
        return ""


def _label(host: str) -> str:
    """The name part of a domain: "acme" for www.acme.co.uk."""
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _squashed(company: str) -> tuple[str, str]:
    words = identity.normalize_company(company).split()
    plain = "".join(w for w in words if w not in _NAME_FILLER)
    return "".join(words), plain


def domain_matches(company: str, host: str) -> bool:
    """Whether ``host`` looks like ``company``'s own domain."""
    if any(marker in host.lower() for marker in _NOT_OFFICIAL):
        return False
    label = re.sub(r"[^a-z0-9]", "", _label(host))
    full, plain = _squashed(company)
    if not label or not full:
        return False
    if label in (full, plain) or any(label == plain + end for end in _DOMAIN_ENDINGS):
        return True
    # A domain that drops the end of a long name: capitalone.com for Capital One Financial.
    return len(label) >= 4 and (plain or full).startswith(label)


def _read(fetcher: Fetcher, url: str, kind: SourceKind) -> Source:
    fetched = fetcher.get(url)
    text, title, findings = pages.page_text(fetched)
    if not text:
        raise FetchError(f"{httpx.URL(fetched.url).host} has no readable text.")
    return _source(kind, text, url=fetched.url, title=title, findings=findings)


def board_source(canonical_key: str, fetcher: Fetcher) -> Source | None:
    """The Greenhouse board's company description, for a ``greenhouse:board:id`` posting."""
    ats, _, rest = canonical_key.partition(":")
    board = rest.partition(":")[0]
    if ats != "greenhouse" or not re.fullmatch(r"[A-Za-z0-9_-]+", board):
        return None
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}"
    try:
        data = fetcher.get_json(url)
    except FetchError:
        return None
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str) or not content.strip():
        return None
    text, _, findings = pages.page_text(Fetched(url, "text/html", html.unescape(content)))
    if not text:
        return None
    return _source("board", text, url=url, title="Careers page", findings=findings)


def site_sources(base: str, fetcher: Fetcher, warnings: list[str]) -> list[Source]:
    """The official site's homepage plus ``base`` itself or its about page."""
    if not _host(base):
        warnings.append(f"{base} is not a web address.")
        return []
    url = httpx.URL(base)
    home = f"{url.scheme}://{url.netloc.decode('ascii')}/"
    found: list[Source] = []
    try:
        found.append(_read(fetcher, home, "site"))
    except FetchError as exc:
        warnings.append(f"Could not read {url.host}: {exc}")
        return found
    others = [base] if url.path not in ("", "/") else [home.rstrip("/") + p for p in _ABOUT_PATHS]
    for candidate in others:
        try:
            found.append(_read(fetcher, candidate, "site"))
            break
        except FetchError:
            continue
    return found


def news_sources(hits: list[web_search.Hit], site_host: str, fetcher: Fetcher) -> list[Source]:
    """Up to `MAX_NEWS` news pages, one per domain, none on the company's own site."""
    found: list[Source] = []
    seen = {_label(site_host)} if site_host else set()
    for hit in hits:
        host = _host(hit.url)
        if len(found) >= MAX_NEWS or not host or any(m in host for m in _NOT_NEWS):
            continue
        if _label(host) in seen:
            continue
        seen.add(_label(host))
        try:
            found.append(_read(fetcher, hit.url, "news"))
        except FetchError:
            continue
    return found


def web_address(url: str) -> str:
    """``url`` with https:// added when the student left the scheme off."""
    url = url.strip()
    return url if "://" in url else f"https://{url}"


def automatic(
    *, company: str, jd_text: str, canonical_key: str, fetcher: Fetcher,
    site_url: str = "",
    search: Callable[[str, int], list[web_search.Hit]] = web_search.search,
) -> Gathered:
    """The posting, the board, the official site and news (sources 1 to 4)."""
    out = Gathered()
    if jd_text.strip() and (posting := posting_source(jd_text)):
        out.sources.append(posting)
    if canonical_key and (board := board_source(canonical_key, fetcher)):
        out.sources.append(board)
    official, news_hits = web_address(site_url) if site_url.strip() else "", []
    queries = web_search.company_queries(company)
    if queries and (provider := web_search.provider()):
        out.searched_with = provider
        try:
            if not official:
                official = next((h.url for h in search(queries[0], 5)
                                 if domain_matches(company, _host(h.url))), "")
            news_hits = search(queries[1], 8)
        except web_search.SearchError as exc:
            out.warnings.append(str(exc))
    if official:
        out.sources += site_sources(official, fetcher, out.warnings)
    site_host = _host(official) if official else ""
    out.sources += news_sources(news_hits, site_host, fetcher)
    return out


def added(*, urls: Sequence[str], notes: Sequence[str], fetcher: Fetcher) -> Gathered:
    """Pages and notes the student adds (source 5)."""
    out = Gathered()
    for url in urls:
        try:
            out.sources.append(_read(fetcher, web_address(url), "page"))
        except FetchError as exc:
            out.warnings.append(f"Could not read {url}: {exc}")
    for note in notes:
        text, findings = pages.clean(note)
        if text:
            out.sources.append(_source("note", text, title="Your note", findings=findings))
    return out
