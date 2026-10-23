"""A fetched page as readable, guarded text. Pure, no network.

HTML goes through the same extraction as job postings (`fetch_jd.extract_fragment_text`:
no scripts, styles, nav, header or footer, hidden elements removed) and every page
through `posting_guard.guard`, so invisible characters are gone and lines aimed at an AI
are flagged. The text is capped at `MAX_CHARS`.
"""

from __future__ import annotations

import html
import re

from resume_tailor.apply.discovery import fetch_jd
from resume_tailor.infra.polite_fetch import Fetched
from resume_tailor.pipeline import posting_guard

MAX_CHARS = 8000
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
#: The document head: its title is kept as the title, never as body text.
_HEAD = re.compile(r"<head\b.*?</head\s*>", re.IGNORECASE | re.DOTALL)


def _tidy(text: str) -> str:
    """One line per paragraph, inner whitespace collapsed, blank lines dropped."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def clean(text: str) -> tuple[str, posting_guard.GuardFindings]:
    """Pasted or extracted text, guarded and capped."""
    text, findings = posting_guard.guard(_tidy(text))
    return text[:MAX_CHARS].strip(), findings


def page_text(fetched: Fetched) -> tuple[str, str, posting_guard.GuardFindings]:
    """``(text, title, findings)`` for one fetched page."""
    if "html" not in fetched.content_type:
        text, findings = clean(fetched.text)
        return text, "", findings
    match = _TITLE.search(fetched.text)
    title = " ".join(html.unescape(match.group(1)).split())[:200] if match else ""
    with fetch_jd.collect_hidden() as hidden:
        body = fetch_jd.extract_fragment_text(_HEAD.sub(" ", fetched.text, count=1))
    text, findings = posting_guard.guard(_tidy(body), hidden=hidden)
    return text[:MAX_CHARS].strip(), title, findings
