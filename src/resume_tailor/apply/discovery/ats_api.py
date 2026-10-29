"""Fetch JD text from public ATS JSON APIs (Greenhouse / Lever / SR / Ashby / Workday).

Never raises — returns an empty `ApiRead` on any failure so ``fetch_jd`` can fall
through to HTTP / CDP. Pure HTTP + HTML unescape; no LLM.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from resume_tailor.apply.discovery import fetch_jd as fetch_jd_mod

SUPPORTED = frozenset({"greenhouse", "lever", "smartrecruiters", "ashby"})


@dataclass(frozen=True)
class ApiRead:
    """What a feed said about one posting: its JD text, or why it is gone (both empty
    when the feed could not tell)."""

    text: str | None = None
    #: Why the feed says the posting no longer exists, e.g. "Greenhouse no longer lists it".
    gone: str = ""

#: Process-lifetime Ashby board cache cleared at the start of each daily run.
_ASHBY_BOARD_CACHE: dict[str, dict[str, Any]] = {}

_TAG_RE = re.compile(r"<[^>]+>")

#: A locale path segment Workday inserts before ``job/…`` (``en-US``, ``en-CA``, …).
_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def clear_ashby_cache() -> None:
    """Drop the in-process Ashby board cache (call at ``run_daily`` start)."""
    _ASHBY_BOARD_CACHE.clear()


def _strip_tags(text: str) -> str:
    """Remove HTML tags and unescape entities."""
    return html.unescape(_TAG_RE.sub(" ", text or ""))


def _get_status_json(
    url: str, *, timeout: float = 15.0, headers: dict[str, str] | None = None
) -> tuple[int | None, Any]:
    """GET ``url``: its status and parsed JSON body (None when the body is not JSON);
    ``(None, None)`` when the request itself failed."""
    try:
        response = httpx.get(url, follow_redirects=True, timeout=timeout, headers=headers)
    except Exception:  # noqa: BLE001
        return None, None
    try:
        return response.status_code, response.json()
    except Exception:  # noqa: BLE001
        return response.status_code, None


def _get_json(
    url: str, *, timeout: float = 15.0, headers: dict[str, str] | None = None
) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return parsed JSON, or ``None`` on any failure."""
    status, data = _get_status_json(url, timeout=timeout, headers=headers)
    return data if status == 200 else None


def _greenhouse(board: str, job_id: str) -> str | None:
    """Fetch Greenhouse job HTML content and extract plain text."""
    url = (
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
        f"?content=true"
    )
    data = _get_json(url)
    if not isinstance(data, dict):
        return None
    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    return fetch_jd_mod.extract_fragment_text(html.unescape(content))


def _greenhouse_by_token(job_id: str) -> ApiRead:
    """A Greenhouse job found by its id alone, for a ``gh_jid`` on a company's own careers
    page, where the board in the key is only a guess read from the page's path.

    Greenhouse ids are global: its embed page answers 404 for a job that closed and
    redirects an open one to ``…/embed/job_app?for=<board>&token=<id>`` (2026-10-29).
    """
    url = f"https://boards.greenhouse.io/embed/job_app?token={job_id}"
    try:
        response = httpx.get(url, follow_redirects=True, timeout=15.0)
    except Exception:  # noqa: BLE001
        return ApiRead()
    if response.status_code == 404:
        return ApiRead(gone="Greenhouse no longer lists it")
    if response.status_code != 200:
        return ApiRead()
    board = (parse_qs(urlparse(str(response.url)).query).get("for") or [""])[0]
    return ApiRead(text=_greenhouse(board, job_id)) if board else ApiRead()


def _lever(company: str, job_id: str) -> str | None:
    """Fetch Lever posting plain text + list sections."""
    url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
    data = _get_json(url)
    if not isinstance(data, dict):
        return None
    parts: list[str] = []
    desc = data.get("descriptionPlain") or ""
    if desc:
        parts.append(str(desc))
    for block in data.get("lists") or []:
        if not isinstance(block, dict):
            continue
        title = block.get("text") or ""
        body = _strip_tags(str(block.get("content") or ""))
        if title:
            parts.append(str(title))
        if body:
            parts.append(body)
    extra = data.get("additionalPlain") or ""
    if extra:
        parts.append(str(extra))
    text = "\n\n".join(p for p in parts if p.strip())
    return text or None


def _smartrecruiters(company: str, job_id: str) -> str | None:
    """Fetch SmartRecruiters jobAd section texts."""
    url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{job_id}"
    data = _get_json(url)
    if not isinstance(data, dict):
        return None
    sections = (data.get("jobAd") or {}).get("sections") or {}
    parts: list[str] = []
    if isinstance(sections, dict):
        for section in sections.values():
            if isinstance(section, dict) and section.get("text"):
                parts.append(_strip_tags(str(section["text"])))
    text = "\n\n".join(p for p in parts if p.strip())
    return text or None


def _ashby(company: str, job_id: str) -> str | None:
    """Fetch Ashby board once, then locate the job by id."""
    if company not in _ASHBY_BOARD_CACHE:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
        data = _get_json(url)
        if not isinstance(data, dict):
            return None
        _ASHBY_BOARD_CACHE[company] = data
    board = _ASHBY_BOARD_CACHE[company]
    jobs = board.get("jobs") or []
    if not isinstance(jobs, list):
        return None
    for job in jobs:
        if not isinstance(job, dict):
            continue
        if str(job.get("id") or "") != job_id:
            continue
        plain = job.get("descriptionPlain")
        if isinstance(plain, str) and plain.strip():
            return plain
        html_body = job.get("descriptionHtml")
        if isinstance(html_body, str) and html_body.strip():
            return fetch_jd_mod.extract_fragment_text(html_body)
        return None
    return None


def _workday_api_url(url: str) -> str | None:
    """Return the Workday ``wday/cxs`` JSON address for a posting URL, or ``None``.

    Every ``myworkdayjobs.com`` posting has a matching JSON address at
    ``/wday/cxs/<tenant>/<path>``, one path segment shorter when the URL carries a
    leading locale (``en-US``, ``en-CA``, …).
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host.endswith(".myworkdayjobs.com"):
        return None
    tenant = host.split(".")[0]
    segments = [s for s in parsed.path.split("/") if s]
    if segments and _LOCALE_SEGMENT.match(segments[0]):
        segments = segments[1:]
    if "job" not in segments:
        return None
    return f"https://{host}/wday/cxs/{tenant}/{'/'.join(segments)}"


def workday_posting(url: str) -> ApiRead:
    """A Workday posting's description from its JSON feed.

    ``gone`` is set when the feed refuses the posting with ``403`` / ``S22`` ("permission
    denied"), which is how Workday answers for a posting it took down: on 64 live URLs
    (2026-10-29) a 403 always came with a page holding no job data, and a 200 never did.
    A hint only — `fetch_jd` confirms it against the page. A 404 is not the same: two
    open postings answered 404 from the feed. Text shorter than
    ``fetch_jd._MIN_JD_CHARS`` is treated as a miss.
    """
    api_url = _workday_api_url(url)
    if api_url is None:
        return ApiRead()
    status, data = _get_status_json(api_url, headers={"Accept": "application/json"})
    if status == 403 and isinstance(data, dict) and data.get("errorCode") == "S22":
        return ApiRead(gone="Workday no longer lists it")
    if status != 200 or not isinstance(data, dict):
        return ApiRead()
    info = data.get("jobPostingInfo")
    if not isinstance(info, dict):
        return ApiRead()
    description = info.get("jobDescription")
    if not isinstance(description, str) or not description.strip():
        return ApiRead()
    text = fetch_jd_mod.extract_fragment_text(html.unescape(description))
    if len(text.strip()) < fetch_jd_mod._MIN_JD_CHARS:  # noqa: SLF001
        return ApiRead()
    return ApiRead(text=text)


def fetch_posting(canonical_key: str) -> ApiRead:
    """JD text for ``ats:slug:id``, or why the feed says it is gone; empty to fall through.

    Text shorter than ``fetch_jd._MIN_JD_CHARS`` is treated as a miss.
    """
    parts = canonical_key.split(":", 2)
    if len(parts) != 3:
        return ApiRead()
    ats, slug, job_id = parts
    if ats not in SUPPORTED:
        return ApiRead()
    text: str | None = None
    if ats == "greenhouse":
        text = _greenhouse(slug, job_id)
        if text is None and job_id.isdigit():
            found = _greenhouse_by_token(job_id)
            if found.gone:
                return found
            text = found.text
    elif ats == "lever":
        text = _lever(slug, job_id)
    elif ats == "smartrecruiters":
        text = _smartrecruiters(slug, job_id)
    elif ats == "ashby":
        text = _ashby(slug, job_id)
    if text is None or len(text.strip()) < fetch_jd_mod._MIN_JD_CHARS:  # noqa: SLF001
        return ApiRead()
    return ApiRead(text=text)
