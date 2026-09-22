"""Fetch JD text from public ATS JSON APIs (Greenhouse / Lever / SR / Ashby).

Never raises — returns ``None`` on any failure so ``fetch_jd`` can fall through
to HTTP / CDP. Pure HTTP + HTML unescape; no LLM.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from resume_tailor.apply import fetch_jd as fetch_jd_mod

SUPPORTED = frozenset({"greenhouse", "lever", "smartrecruiters", "ashby"})

#: Process-lifetime Ashby board cache cleared at the start of each daily run.
_ASHBY_BOARD_CACHE: dict[str, dict[str, Any]] = {}

_TAG_RE = re.compile(r"<[^>]+>")


def clear_ashby_cache() -> None:
    """Drop the in-process Ashby board cache (call at ``run_daily`` start)."""
    _ASHBY_BOARD_CACHE.clear()


def _strip_tags(text: str) -> str:
    """Remove HTML tags and unescape entities."""
    return html.unescape(_TAG_RE.sub(" ", text or ""))


def _get_json(url: str, *, timeout: float = 15.0) -> dict[str, Any] | list[Any] | None:
    """GET ``url`` and return parsed JSON, or ``None`` on any failure."""
    try:
        response = httpx.get(url, follow_redirects=True, timeout=timeout)
        if response.status_code != 200:
            return None
        return response.json()
    except Exception:  # noqa: BLE001
        return None


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
    return fetch_jd_mod.extract_text(html.unescape(content))


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
            return fetch_jd_mod.extract_text(html_body)
        return None
    return None


def fetch_posting_text(canonical_key: str) -> str | None:
    """Return JD text for ``ats:slug:id``, or ``None`` to fall through.

    Text shorter than ``fetch_jd._MIN_JD_CHARS`` is treated as a miss.
    """
    parts = canonical_key.split(":", 2)
    if len(parts) != 3:
        return None
    ats, slug, job_id = parts
    if ats not in SUPPORTED:
        return None
    text: str | None = None
    if ats == "greenhouse":
        text = _greenhouse(slug, job_id)
    elif ats == "lever":
        text = _lever(slug, job_id)
    elif ats == "smartrecruiters":
        text = _smartrecruiters(slug, job_id)
    elif ats == "ashby":
        text = _ashby(slug, job_id)
    if text is None:
        return None
    if len(text.strip()) < fetch_jd_mod._MIN_JD_CHARS:
        return None
    return text
