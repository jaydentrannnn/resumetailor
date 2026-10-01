"""Small, pure checks for awkward postings and forms (plan P4-E).

Each check answers one question with a plain-language reason, or None:

- `closed_posting`: is the posting closed or expired (E13)? Prepare runs it before
  tailoring, so a closed job costs no model calls and ends ``skipped``.
- `form_language`: is the form in a language the filler doesn't handle (E19)? The
  field synonyms are English, so a French form is handed over, not guessed at.
- `bot_block`: did the site refuse us (E21: 403/429 pages, "unusual traffic")? The host
  then rests for an hour (`block_host` / `host_blocked`) so a batch doesn't hammer it.
- `fit_to_limit`: shorten a saved answer to a field's ``maxlength`` at a sentence
  boundary (E18). This is a form limit, not resume truncation, and the field is always
  flagged for review when it happens.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

_CLOSED_PHRASES = re.compile(
    r"no longer accepting applications"
    r"|(?:this|the) (?:job|position|posting|role|requisition) (?:is|has) (?:no longer "
    r"(?:available|open|active)|been (?:filled|closed|removed)|closed|expired)"
    r"|(?:job|position|posting) (?:has )?expired"
    r"|(?:this|the) job (?:you are|you're) looking for (?:is no longer|could not be|was not)"
    r"|position has been filled"
    r"|applications? (?:are|is) (?:now )?closed"
    r"|we are no longer (?:accepting|hiring)",
    re.IGNORECASE,
)
#: Paths a closed posting commonly redirects to: the careers home or the job list.
_HOME_PATHS = frozenset({"", "/", "/careers", "/jobs", "/search", "/job-search", "/en-us/careers"})

_BOT_PHRASES = re.compile(
    r"unusual traffic|are you a robot|verify you are (?:a )?human|access denied"
    r"|request (?:has been )?blocked|too many requests|rate limit(?:ed)?"
    r"|attention required! \| cloudflare|sorry, you have been blocked",
    re.IGNORECASE,
)

HOST_COOLDOWN = timedelta(hours=1)
_blocked: dict[str, datetime] = {}
_blocked_lock = threading.Lock()


def closed_posting(
    text: str,
    *,
    status: int | None = None,
    final_url: str = "",
    requested_url: str = "",
) -> str | None:
    """Why the posting looks closed, or None when it looks open.

    Only the first part of the page is read for closing phrases. A long, real JD that
    mentions "applications are closed on weekends" in its benefits section is not
    enough; a closing banner sits at the top.
    """
    if status in (404, 410):
        return f"Posting closed (the page answered {status})"
    head = (text or "")[:1500]
    match = _CLOSED_PHRASES.search(head)
    if match:
        return f"Posting closed ({match.group(0).strip()!r} on the page)"
    if final_url and requested_url:
        asked, landed = urlsplit(requested_url), urlsplit(final_url)
        same_site = (asked.hostname or "").lower() == (landed.hostname or "").lower()
        if (
            same_site
            and landed.path.rstrip("/").lower() in _HOME_PATHS
            and asked.path.rstrip("/").lower() not in _HOME_PATHS
        ):
            return "Posting closed (redirected to the careers home page)"
    return None


def form_language(lang: str) -> str | None:
    """A handoff reason for a non-English form (``<html lang>``), else None.

    An empty or missing ``lang`` counts as English: most US forms never set it.
    """
    code = (lang or "").strip().lower().replace("_", "-")
    if not code or code.startswith("en") or code in {"und", "mul", "zxx"}:
        return None
    return f"The form is in another language ({code}); only English forms are filled"


def bot_block(*, status: int | None = None, title: str = "", body: str = "") -> str | None:
    """A reason when the site refused an automated visitor, else None."""
    if status in (403, 429):
        return f"The site refused the visit (HTTP {status})"
    head = f"{title}\n{(body or '')[:2000]}"
    match = _BOT_PHRASES.search(head)
    if match:
        return f"The site blocked automated access ({match.group(0).strip()!r})"
    return None


def _host(url_or_host: str) -> str:
    text = (url_or_host or "").strip().lower()
    return (urlsplit(text).hostname or "") if "://" in text else text


def block_host(url_or_host: str, *, now: datetime | None = None) -> None:
    host = _host(url_or_host)
    if host:
        with _blocked_lock:
            _blocked[host] = (now or datetime.now(UTC)) + HOST_COOLDOWN


def host_blocked(url_or_host: str, *, now: datetime | None = None) -> timedelta | None:
    """Time left on a host's rest period, or None when it may be visited."""
    host = _host(url_or_host)
    if not host:
        return None
    now = now or datetime.now(UTC)
    with _blocked_lock:
        until = _blocked.get(host)
        if until is None:
            return None
        if until <= now:
            del _blocked[host]
            return None
        return until - now


def reset_hosts() -> None:
    with _blocked_lock:
        _blocked.clear()


_SENTENCE_END = re.compile(r"[.!?](?:[\"')\]]*)(?=\s|$)")


def fit_to_limit(text: str, limit: int) -> tuple[str, bool]:
    """``(text, shortened)``: ``text`` cut to ``limit`` characters at a sentence end.

    Falls back to the last whole word when the first sentence alone is too long, and
    returns ("", True) when not even one word fits.
    """
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text, False
    window = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(window)]
    if ends:
        return window[: ends[-1]].strip(), True
    if text[limit].isspace():
        cut = window
    else:
        parts = window.rsplit(None, 1)
        cut = parts[0] if len(parts) == 2 else ""
    return cut.rstrip(" ,;:-"), True
