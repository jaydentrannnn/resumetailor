"""Answers the student corrected during review, reused by later fills (plan P3-A).

When the student fixes a field in the review flow (`review.correct`), the label and the
value they chose are remembered. The next form that asks the same question, on any
posting, gets that answer before the model is asked. Lookup order in a fill is: profile
fact → remembered answer → profile ``custom_answers`` → model.

Labels are matched after normalisation (`normalize_label`): lower case, punctuation
dropped, whitespace collapsed, and the posting's company name replaced with
``{company}``. So "Why do you want to work at Acme?" and "Why do you want to work at
Beta?" are the same question. The *answer* is not rewritten, though. An answer that
names the company it was written for is never reused for another company; it comes
back as `Recall.needs_review` instead.

Never stored: equal-opportunity answers (they come only from the profile), passwords,
one-time codes, and other credentials or identity numbers. Rows live in the
workspace's SQLite database next to the applications.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.storage import db

#: Labels whose answers must never be remembered or recalled.
_NEVER = re.compile(
    r"gender|\bsex\b|pronoun|transgender|sexual orientation|lgbt|race\b|racial|ethnic|"
    r"hispanic|latin[oax]|veteran|disabilit|"
    r"password|passcode|verification|one.time|\botp\b|security code|\bpin\b|"
    r"social security|\bssn\b|\bsin\b|date of birth|birth ?date|passport|"
    r"driver.?s licen[cs]e number|signature|initials",
    re.IGNORECASE,
)
#: Canonical field keys owned by the profile's equal-opportunity section.
_EEO_KEYS = frozenset(
    {"gender", "race", "race_detail", "ethnicity", "hispanic", "hispanic_latino", "veteran",
     "veteran_status", "disability", "disability_status", "sexual_orientation", "transgender",
     "pronouns"}
)  # fmt: skip
_COMPANY_SUFFIX = re.compile(
    r"[,\s]+(?:inc|llc|ltd|corp|corporation|co|company|plc|lp|llp|group|holdings)\.?$",
    re.IGNORECASE,
)
MAX_ANSWER_CHARS = 5000


class SavedAnswer(BaseModel):
    """One remembered answer, as the Profile page lists it."""

    id: int
    label: str
    answer: str
    ats: str = ""
    company: str = ""
    source: str = "correction"
    uses: int = 0
    updated_at: str = ""


@dataclass(frozen=True)
class Recall:
    """A remembered answer for a question, or why it can't be used as-is."""

    answer: str
    id: int
    #: The answer names the company it was written for, which isn't this one.
    needs_review: bool = False
    reason: str = ""


def _conn() -> sqlite3.Connection:
    return db.connect(db.db_path(Path(config.APPLICATIONS_PATH).parent))


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def company_name(company: str) -> str:
    """The company as it appears in prose: "Acme Corp." → "Acme"."""
    name = (company or "").strip()
    while True:
        shorter = _COMPANY_SUFFIX.sub("", name).strip()
        if shorter == name:
            return name
        name = shorter


def _mentions(text: str, company: str) -> bool:
    name = company_name(company)
    if len(name) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE) is not None


def normalize_label(label: str, company: str = "") -> str:
    """Lower case, company → ``{company}``, punctuation dropped, whitespace collapsed."""
    text = (label or "").strip()
    name = company_name(company)
    if len(name) >= 2:
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " {company} ", text, flags=re.I)
    text = text.lower()
    text = re.sub(r"[^\w\s{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def storable(label: str, *, canonical_key: str = "", input_type: str = "") -> bool:
    """Whether an answer to this question may be remembered at all."""
    if not label.strip() or canonical_key in _EEO_KEYS:
        return False
    if input_type.casefold() == "password":
        return False
    return _NEVER.search(label) is None


def remember(
    label: str,
    answer: str,
    *,
    company: str = "",
    ats: str = "",
    canonical_key: str = "",
    input_type: str = "",
    source: str = "correction",
) -> SavedAnswer | None:
    """Save (or replace) the answer to ``label``; None when it must not be stored."""
    answer = (answer or "").strip()
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        return None
    if not storable(label, canonical_key=canonical_key, input_type=input_type):
        return None
    norm = normalize_label(label, company)
    if not norm:
        return None
    now = _now()
    conn = _conn()
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO answer_memory(label_norm, ats, label, answer, company, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(label_norm, ats) DO UPDATE SET label = excluded.label, "
            "answer = excluded.answer, company = excluded.company, "
            "source = excluded.source, updated_at = excluded.updated_at",
            (norm, (ats or "").lower(), label.strip(), answer, company.strip(), source, now, now),
        )
        row = conn.execute(
            "SELECT id FROM answer_memory WHERE label_norm = ? AND ats = ?",
            (norm, (ats or "").lower()),
        ).fetchone()
    return get(int(row[0]))


def recall(
    label: str, *, company: str = "", ats: str = "", canonical_key: str = ""
) -> Recall | None:
    """The remembered answer to ``label``: same ATS first, then any; None when unknown."""
    if not storable(label, canonical_key=canonical_key):
        return None
    norm = normalize_label(label, company)
    if not norm:
        return None
    conn = _conn()
    row = conn.execute(
        "SELECT id, answer, company FROM answer_memory WHERE label_norm = ? "
        "ORDER BY (ats = ?) DESC, updated_at DESC, id DESC LIMIT 1",
        (norm, (ats or "").lower()),
    ).fetchone()
    if row is None:
        return None
    row_id, answer, origin = int(row[0]), str(row[1]), str(row[2])
    if (
        origin
        and company_name(origin).casefold() != company_name(company).casefold()
        and _mentions(answer, origin)
    ):
        return Recall(
            answer=answer,
            id=row_id,
            needs_review=True,
            reason=f"Your saved answer mentions {company_name(origin)}; check it for this company.",
        )
    with db.transaction(conn):
        conn.execute("UPDATE answer_memory SET uses = uses + 1 WHERE id = ?", (row_id,))
    return Recall(answer=answer, id=row_id)


def _row(values) -> SavedAnswer:
    keys = ("id", "label", "answer", "ats", "company", "source", "uses", "updated_at")
    return SavedAnswer(**dict(zip(keys, values, strict=True)))


_COLUMNS = "id, label, answer, ats, company, source, uses, updated_at"


def get(answer_id: int) -> SavedAnswer | None:
    row = (
        _conn()
        .execute(f"SELECT {_COLUMNS} FROM answer_memory WHERE id = ?", (answer_id,))
        .fetchone()
    )
    return _row(row) if row else None


def list_answers() -> list[SavedAnswer]:
    rows = (
        _conn()
        .execute(f"SELECT {_COLUMNS} FROM answer_memory ORDER BY updated_at DESC, id DESC")
        .fetchall()
    )
    return [_row(row) for row in rows]


def update(answer_id: int, answer: str) -> SavedAnswer:
    """Replace a saved answer's text (the Profile page's edit). Raises `KeyError`."""
    answer = (answer or "").strip()
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        raise ValueError(f"An answer must be 1 to {MAX_ANSWER_CHARS} characters.")
    conn = _conn()
    with db.transaction(conn):
        changed = conn.execute(
            "UPDATE answer_memory SET answer = ?, source = 'edited', updated_at = ? WHERE id = ?",
            (answer, _now(), answer_id),
        ).rowcount
    if not changed:
        raise KeyError(answer_id)
    saved = get(answer_id)
    assert saved is not None
    return saved


def delete(answer_id: int) -> None:
    conn = _conn()
    with db.transaction(conn):
        if not conn.execute("DELETE FROM answer_memory WHERE id = ?", (answer_id,)).rowcount:
            raise KeyError(answer_id)
