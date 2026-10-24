"""Job email read straight from the student's mailbox over IMAP, read-only. No LLM.

Beside the Claude Desktop path (`mail_inbox`, fed by the MCP server), for mailboxes that
connector cannot reach. The reader never changes the mailbox: every folder is opened
with EXAMINE (read-only) and every fetch is a ``BODY.PEEK``, so nothing is marked read;
`_Box` exposes no command that flags, moves, copies or deletes. Login is over TLS only
(implicit on 993, STARTTLS on 143), never plain text.

Only job mail is read past its headers. Headers since a date are fetched for every
folder except sent, drafts and trash; a message gets its body fetched only when its
sender is an application or hiring system (`mail_signals.ATS_DOMAINS`, `HIRING_HOSTS`),
it names a company the student applied to, or its subject reads like hiring mail.
Bodies are reduced to guarded plain text (`posting_guard`), capped like a Claude
Desktop post, and handed to `mail_inbox.ingest`; nothing raw is kept.
"""

from __future__ import annotations

import contextlib
import email
import email.policy
import imaplib
import logging
import re
import ssl
from collections.abc import Iterable, Iterator
from datetime import date
from email.message import EmailMessage

from pydantic import BaseModel, Field

from resume_tailor.apply.discovery import fetch_jd, identity
from resume_tailor.pipeline import posting_guard

from . import mail_inbox, mail_signals

_log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
#: Bytes of a job email fetched: its text comes first, attachments are cut off.
BODY_BYTES = 300_000
#: Most bodies one check fetches.
MAX_BODIES = 2000
_BATCH = 200
_STARTTLS_PORT = 143
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_HEADERS = "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
_BODY = f"(BODY.PEEK[]<0.{BODY_BYTES}>)"
#: Folders of the student's own or deleted mail, and duplicates of other folders.
_SKIP_FLAGS = frozenset({"\\sent", "\\drafts", "\\trash", "\\noselect", "\\flagged",
                         "\\important", "\\nonexistent"})
_SKIP_NAMES = re.compile(r"(?:^|/|\.)(?:sent|drafts?|trash|deleted|bin|outbox)\b", re.I)
_LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
_UID = re.compile(rb"\bUID (\d+)")
_JOB_SUBJECT = re.compile(
    r"\b(?:application|applying|applied|candidacy|candidate|interview|assessment|offer|"
    r"recruit\w*|hiring|position|talent|phone screen|thanks? (?:you )?for your interest)\b",
    re.I,
)


class MailAccount(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.-]+$")
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)


class MailError(RuntimeError):
    """A check that could not read the mailbox; the message is for the student."""


class MailAuthError(MailError):
    pass


class MailConnectError(MailError):
    pass


class _Box:
    """The only IMAP calls the reader makes: none of them can change the mailbox."""

    def __init__(self, account: MailAccount) -> None:
        context = ssl.create_default_context()
        if account.port == _STARTTLS_PORT:
            self._imap = imaplib.IMAP4(account.host, account.port, timeout=TIMEOUT_SECONDS)
            self._imap.starttls(ssl_context=context)
        else:
            self._imap = imaplib.IMAP4_SSL(account.host, account.port, ssl_context=context,
                                           timeout=TIMEOUT_SECONDS)

    def login(self, username: str, password: str) -> None:
        self._imap.login(username, password)

    def folders(self) -> list[bytes]:
        status, lines = self._imap.list()
        return [line for line in lines or [] if line] if status == "OK" else []

    def examine(self, name: bytes) -> bytes:
        """Open ``name`` read-only; returns its UIDVALIDITY (b"" when not given)."""
        status, _ = self._imap.select(_quote(name), readonly=True)
        if status != "OK":
            return b""
        _, value = self._imap.response("UIDVALIDITY")
        return (value or [b""])[0] or b""

    def search_since(self, since: date) -> list[bytes]:
        day = f"{since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}"
        status, data = self._imap.uid("SEARCH", None, "SINCE", day)
        return (data[0] or b"").split() if status == "OK" and data else []

    def fetch(self, uids: list[bytes], spec: str) -> list[tuple[bytes, bytes]]:
        """``(uid, bytes)`` per message; ``spec`` is always a ``BODY.PEEK`` read."""
        if "BODY.PEEK" not in spec:
            raise ValueError("Only BODY.PEEK reads are allowed")
        status, data = self._imap.uid("FETCH", b",".join(uids).decode(), spec)
        if status != "OK":
            return []
        return [(uid.group(1), item[1]) for item in data or []
                if isinstance(item, tuple) and (uid := _UID.search(item[0]))]

    def logout(self) -> None:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):  # Already gone.
            self._imap.logout()


def _quote(name: bytes) -> str:
    text = name.decode("ascii", "replace")
    if text.startswith('"') and text.endswith('"'):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def readable_folders(lines: Iterable[bytes | tuple]) -> list[bytes]:
    """Folder names from LIST lines, minus sent, drafts, trash and duplicates."""
    names = []
    for line in lines:
        # A name sent as a literal arrives as (b'(\\Flags) "/" {5}', b'Inbox').
        head, literal = (line[0], line[1]) if isinstance(line, tuple) else (line, None)
        if not (found := _LIST_LINE.match(head)):
            continue
        name = literal if literal is not None else found.group("name").strip()
        flags = {f.lower() for f in found.group("flags").decode("ascii", "replace").split()}
        plain = name.strip(b'"').decode("ascii", "replace")
        if flags & _SKIP_FLAGS or _SKIP_NAMES.search(plain):
            continue
        names.append(name)
    return names


def company_terms(companies: Iterable[str]) -> list[list[str]]:
    """Each company's name as words, for `wanted` (common words like "Inc" dropped)."""
    terms = []
    for company in companies:
        words = mail_signals._words(identity.normalize_company(company))
        if any(w not in mail_signals._STOP for w in words):
            terms.append(words)
    return terms


def wanted(sender: str, subject: str, companies: list[list[str]]) -> bool:
    """Whether a message's headers look like hiring mail worth reading the body of."""
    name, address = mail_signals.sender_parts(sender)
    domain = address.rpartition("@")[2].lower()
    if mail_signals.hiring_sender(domain) or _JOB_SUBJECT.search(subject):
        return True
    words = mail_signals._words(f"{name}\n{subject}")
    squashed = domain.replace("-", "")
    for company in companies:
        if mail_signals._phrase_in(company, words):
            return True
        first = next(w for w in company if w not in mail_signals._STOP)
        if len(first) >= 4 and first in squashed:
            return True
    return False


def _text(message: EmailMessage) -> str:
    """The email's text, as guarded plain text (HTML reduced like a posting)."""
    try:
        part = message.get_body(preferencelist=("plain", "html"))
        content = part.get_content() if part is not None else ""
    except (LookupError, ValueError, AttributeError, UnicodeError):
        return ""
    if part is not None and part.get_content_type() == "text/html":
        with fetch_jd.collect_hidden() as hidden:
            content = fetch_jd.extract_fragment_text(content)
        text, _ = posting_guard.guard(content, hidden=hidden)
    else:
        text, _ = posting_guard.guard(str(content))
    return text


def _headers(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)


def _header(message: EmailMessage, name: str) -> str:
    try:
        return " ".join(str(message.get(name, "") or "").split())
    except (ValueError, IndexError):  # A malformed header the parser could not decode.
        return ""


def _incoming(key: str, headers: EmailMessage, raw_body: bytes) -> mail_inbox.IncomingMail:
    body = _text(email.message_from_bytes(raw_body, policy=email.policy.default))
    return mail_inbox.IncomingMail(
        message_id=key[:300], sender=_header(headers, "From")[:300],
        subject=_header(headers, "Subject")[:500], date=_header(headers, "Date")[:100],
        body=body[:4000],
    )


def _batches(items: list[bytes]) -> Iterator[list[bytes]]:
    for start in range(0, len(items), _BATCH):
        yield items[start:start + _BATCH]


def _open(account: MailAccount, password: str) -> _Box:
    try:
        box = _Box(account)
    except imaplib.IMAP4.error as exc:  # Something answered, but not an IMAP server.
        pop = " Port 995 is for POP3." if account.port == 995 else ""
        raise MailConnectError(
            f"{account.host} answered on port {account.port}, but not as an IMAP server.{pop} "
            "IMAP over TLS uses port 993."
        ) from exc
    except OSError as exc:  # ssl.SSLError included.
        raise MailConnectError(
            f"Could not reach {account.host} on port {account.port}. Check the server name "
            "and port (993 for IMAP over TLS)."
        ) from exc
    try:
        box.login(account.username, password)
    except imaplib.IMAP4.error as exc:
        box.logout()
        raise MailAuthError("The mail server refused that username or password.") from exc
    except OSError as exc:
        box.logout()
        raise MailConnectError(f"The connection to {account.host} dropped.") from exc
    return box


def test(account: MailAccount, password: str) -> int:
    """Log in and count the readable folders. Raises `MailError`."""
    box = _open(account, password)
    try:
        return len(readable_folders(box.folders()))
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailConnectError(f"The connection to {account.host} dropped.") from exc
    finally:
        box.logout()


def fetch(
    account: MailAccount, password: str, *, since: date, companies: Iterable[str] = (),
) -> list[mail_inbox.IncomingMail]:
    """Hiring mail received since ``since`` in every readable folder, oldest first.

    Raises:
        MailAuthError: The server refused the login.
        MailConnectError: The server could not be reached, or the connection dropped.
    """
    terms = company_terms(companies)
    box = _open(account, password)
    found: dict[str, tuple[str, mail_inbox.IncomingMail]] = {}
    bodies = 0
    try:
        for folder in readable_folders(box.folders()):
            validity = box.examine(folder)
            uids = box.search_since(since)
            keep: dict[bytes, tuple[str, EmailMessage]] = {}
            for batch in _batches(uids):
                for uid, raw in box.fetch(batch, _HEADERS):
                    headers = _headers(raw)
                    key = _header(headers, "Message-ID") or (
                        f"imap:{folder.strip(b'\"').decode('ascii', 'replace')}:"
                        f"{validity.decode()}:"
                        f"{uid.decode()}")
                    if key in found or not wanted(_header(headers, "From"),
                                                  _header(headers, "Subject"), terms):
                        continue
                    keep[uid] = (key, headers)
            for batch in _batches(list(keep)[: max(0, MAX_BODIES - bodies)]):
                for uid, raw in box.fetch(batch, _BODY):
                    key, headers = keep[uid]
                    mail = _incoming(key, headers, raw)
                    found[key] = (mail_signals.received_on(mail.date) or "", mail)
                    bodies += 1
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailConnectError(f"The connection to {account.host} dropped.") from exc
    finally:
        box.logout()
    _log.info("mail check read %d job emails", len(found))
    return [mail for _, mail in sorted(found.values(), key=lambda item: item[0])]
