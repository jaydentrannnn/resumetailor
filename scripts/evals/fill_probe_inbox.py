"""The test inbox for `fill_probe.py` account targets (eval-only, standard library only).

Test accounts sign up as ``<user>+rt<site digest>@gmail.com``: one stable alias per site,
so a rerun signs in to the account the first run made. `wait_for` polls the inbox over
IMAP (Gmail, an app password) for mail to that alias since a moment, and `extract` reads a
verification code or link out of it. Credentials come from
``%LOCALAPPDATA%/ResumeTailorData/evals/test_inbox.env`` (``PROBE_IMAP_USER``,
``PROBE_IMAP_PASSWORD``) and are never printed.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import html
import imaplib
import os
import re
import time
from dataclasses import dataclass
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path

ENV_FILE = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "ResumeTailorData" / "evals" / "test_inbox.env"
)
_HOST = "imap.gmail.com"
#: A code is 4-8 characters with at least one digit, set near the word "code".
_CODE_NEAR = re.compile(
    r"(?:code|passcode|pin|one[- ]time)\W{0,5}(?:is\W{1,3})?\b([A-Z0-9]{4,8})\b|"
    r"\b([A-Z0-9]{4,8})\b[^A-Za-z0-9]{0,20}(?:is your|as your)[^.]{0,30}code",
    re.I,
)
_LINK = re.compile(r"https://[^\s\"'<>]+", re.I)
_VERIFY_WORDS = re.compile(r"verif|confirm|activat|validat|token|account", re.I)
_SKIP_LINK = re.compile(
    r"unsubscribe|privacy|terms|facebook|twitter|linkedin|\.(?:png|jpe?g|gif)\b", re.I
)


@dataclass(frozen=True)
class Found:
    code: str = ""
    link: str = ""


def credentials(path: Path = ENV_FILE) -> tuple[str, str]:
    """(user, app password) from the env file, else the process environment."""
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep:
                values[name.strip()] = value.strip().strip('"')
    user = values.get("PROBE_IMAP_USER") or os.environ.get("PROBE_IMAP_USER", "")
    password = values.get("PROBE_IMAP_PASSWORD") or os.environ.get("PROBE_IMAP_PASSWORD", "")
    return user, password.replace(" ", "")


def alias(user: str, site: str) -> str:
    """The stable plus-address for one site's test account."""
    local, _, domain = user.partition("@")
    digest = hashlib.sha256(site.casefold().encode()).hexdigest()[:6]
    return f"{local}+rt{digest}@{domain}"


def _text(message: Message) -> str:
    parts = []
    for part in message.walk() if message.is_multipart() else [message]:
        ctype = part.get_content_type()
        if ctype not in {"text/plain", "text/html"}:
            continue
        try:
            body = part.get_content()
        except Exception:  # noqa: BLE001 - an unknown charset
            body = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if ctype == "text/html":
            links = " ".join(re.findall(r'href=["\']([^"\']+)', body, re.I))
            body = html.unescape(re.sub(r"<[^>]+>", " ", body)) + " " + html.unescape(links)
        parts.append(body)
    return " ".join(parts)


def extract(message: Message) -> Found:
    """The verification code or link a message carries ("" when none is clear)."""
    subject = str(message.get("Subject") or "")
    body = _text(message)
    code = ""
    for match in _CODE_NEAR.finditer(subject + " \n " + body):
        candidate = match.group(1) or match.group(2) or ""
        if re.search(r"\d", candidate):
            code = candidate
            break
    links = [u.rstrip(").,;") for u in _LINK.findall(body) if not _SKIP_LINK.search(u)]
    link = next((u for u in links if _VERIFY_WORDS.search(u)), "")
    return Found(code=code, link=link)


def _messages_to(box: imaplib.IMAP4_SSL, to: str, since: float) -> list[Message]:
    box.select("INBOX")
    day = time.strftime("%d-%b-%Y", time.gmtime(since - 86400))
    status, data = box.search(None, "TO", f'"{to}"', "SINCE", day)
    if status != "OK" or not data or not data[0]:
        return []
    found = []
    for number in reversed(data[0].split()[-10:]):
        status, fetched = box.fetch(number, "(RFC822)")
        if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
            continue
        message = email.message_from_bytes(fetched[0][1], policy=email.policy.default)
        with_date = message.get("Date")
        try:
            sent = parsedate_to_datetime(str(with_date)).timestamp() if with_date else since
        except (TypeError, ValueError):
            sent = since
        if sent >= since - 60:
            found.append(message)
    return found


def wait_for(to: str, since: float, *, timeout_s: float = 180, every_s: float = 10) -> Found:
    """Poll for a verification code or link sent to ``to`` after ``since`` (epoch s)."""
    user, password = credentials()
    if not (user and password):
        raise RuntimeError(f"no test inbox credentials in {ENV_FILE}")
    stop = time.time() + timeout_s
    while True:
        with imaplib.IMAP4_SSL(_HOST) as box:
            box.login(user, password)
            for message in _messages_to(box, to, since):
                found = extract(message)
                if found.code or found.link:
                    return found
        if time.time() >= stop:
            return Found()
        time.sleep(every_s)
