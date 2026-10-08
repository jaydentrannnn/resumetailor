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
one-time codes, and other credentials or identity numbers, and questions a profile field
already answers (`profile_key`): those corrections fill the blank profile field instead
(`save_to_profile`), so the Profile page never shows one fact twice. Rows live in the
workspace's SQLite database next to the applications, one per (question, ATS); the
Profile page sees them grouped by question (`list_answers`).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from resume_tailor import config
from resume_tailor.storage import db

_log = logging.getLogger(__name__)

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
#: A profile question is a short label ("Middle Name", "How did you hear about us?").
#: Longer prompts that merely mention a school or a city are questions of their own.
_PROFILE_LABEL_WORDS = 8
_REFERRAL = re.compile(r"referred by|referral name|who referred you|name of (?:your |the )?referr", re.I)
#: Profile text fields a correction may fill when blank: canonical key -> profile attribute.
_PROFILE_TEXT: dict[str, str] = {
    key: key for key in (
        "first_name", "middle_name", "last_name", "preferred_name", "email", "phone",
        "linkedin_url", "github_url", "portfolio_url", "address_line1", "address_line2",
        "city", "state", "postal_code", "country", "earliest_start", "notice_period",
        "location_preference", "authorization_country", "referred_by", "school_email",
        "highest_education_obtained",
    )
}  # fmt: skip
#: The one-off pass that moved profile-duplicate rows out (`cleanup_profile_duplicates`).
CLEANUP_MARKER = "answer_memory_cleanup_v1"


class SavedAnswer(BaseModel):
    """One remembered answer, as the Profile page lists it.

    `list_answers` returns one per question: ``id`` and the text are the most recent
    row's, ``ids`` every row for that question, ``sites`` the ATSs it was answered on,
    and ``differs`` whether those rows disagree.
    """

    id: int
    label: str
    answer: str
    ats: str = ""
    company: str = ""
    source: str = "correction"
    uses: int = 0
    updated_at: str = ""
    ids: list[int] = []
    sites: list[str] = []
    differs: bool = False


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


def profile_key(label: str, canonical_key: str = "") -> str | None:
    """The profile field that answers this question, if one does.

    ``canonical_key`` (the fill's own classification) wins; otherwise a short label is
    classified by the decision layer every fill uses (`questions`).
    """
    from resume_tailor.apply.answers import questions  # noqa: PLC0415
    from resume_tailor.apply.funnel import packet_profile_fields

    covered = set(packet_profile_fields.PROFILE_FIELDS) | {"referred_by"}
    if canonical_key in covered:
        return canonical_key
    text = (label or "").strip()
    # Education level questions commonly use a full sentence, not a short label.
    from resume_tailor.apply.answers import education  # noqa: PLC0415

    if education.question_key(text) == education.KEY and not education.compound(text):
        return education.KEY
    if not text or len(text.split()) > _PROFILE_LABEL_WORDS:
        return None
    if _REFERRAL.search(text):
        return "referred_by"
    match = questions.classify(questions.Question(text))
    return match.key if match and match.key in covered else None


def is_sensitive(label: str) -> bool:
    """Whether a question is a self-identification or credential one (never copied around)."""
    return _NEVER.search(label or "") is not None


def storable(label: str, *, canonical_key: str = "", input_type: str = "") -> bool:
    """Whether an answer to this question may be remembered at all."""
    if not label.strip() or canonical_key in _EEO_KEYS:
        return False
    if input_type.casefold() == "password":
        return False
    if _NEVER.search(label) is not None:
        return False
    return profile_key(label, canonical_key) is None


#: Yes/No profile questions a correction may fill when still unset: canonical key -> attribute.
_PROFILE_BOOL: dict[str, str] = {
    "over_18": "over_18",
    "authorized_to_work": "authorized_to_work",
    "requires_sponsorship": "requires_sponsorship_now",
    "requires_sponsorship_future": "requires_sponsorship_future",
    "willing_to_relocate": "willing_to_relocate",
    "relatives_at_company": "relatives_at_company",
    "noncompete": "subject_to_noncompete",
    "drivers_license": "drivers_license",
}
#: Date questions: canonical key -> (profile attribute, precision). The form's own wording
#: ("06/14/2027", "June 2027") is read into the stored ISO shape (`content/dates.py`).
_PROFILE_DATE: dict[str, tuple[str, str]] = {
    "earliest_start": ("earliest_start", "day"),
    "graduation_month": ("graduation_date", "month"),
}


def _as_bool(answer: str) -> bool | None:
    head = answer.strip().casefold()
    if head.startswith(("yes", "true")):
        return True
    if head.startswith(("no", "false")):
        return False
    return None


def save_to_profile(key: str, answer: str) -> bool:
    """Put ``answer`` into the blank profile field ``key``; False when not blank.

    A correction to a profile question is what the applicant meant their profile to
    say. A field that already holds a value is left alone: the profile is the source.
    Text, Yes/No and date questions are covered; self-identification answers are not
    (an option's wording is not the profile's canonical value, and they are never
    remembered).
    """
    from resume_tailor.apply.answers import profile as profile_mod  # noqa: PLC0415
    from resume_tailor.content import dates  # noqa: PLC0415

    answer = (answer or "").strip()
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        return False
    current, _seeded = profile_mod.load_profile()
    if key in _PROFILE_BOOL:
        attr, value = _PROFILE_BOOL[key], _as_bool(answer)
        if value is None or getattr(current, attr, None) is not None:
            return False
    elif key in _PROFILE_DATE:
        attr, precision = _PROFILE_DATE[key]
        value = dates.normalize(answer, precision)  # type: ignore[arg-type]
        if dates.parse(value) is None or str(getattr(current, attr, "") or "").strip():
            return False
    elif key in _PROFILE_TEXT:
        attr, value = _PROFILE_TEXT[key], answer
        if str(getattr(current, attr, "") or "").strip():
            return False
    else:
        return False
    # Re-validated, so derived fields (notice period's number, normalized dates) follow.
    updated = profile_mod.ApplicantProfile.model_validate({**current.model_dump(), attr: value})
    profile_mod.save_profile(updated)
    return True


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
    cleanup_profile_duplicates(conn)
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
    """One entry per question, most recently updated first (see `SavedAnswer`)."""
    conn = _conn()
    cleanup_profile_duplicates(conn)
    rows = conn.execute(
        f"SELECT label_norm, {_COLUMNS} FROM answer_memory ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    grouped: dict[str, list[SavedAnswer]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(_row(row[1:]))
    merged: list[SavedAnswer] = []
    for items in grouped.values():
        latest = items[0]
        merged.append(latest.model_copy(update={
            "ids": [item.id for item in items],
            "sites": sorted({item.ats for item in items if item.ats}),
            "differs": len({item.answer.strip() for item in items}) > 1,
            "uses": sum(item.uses for item in items),
        }))
    return merged


def _question_ids(conn: sqlite3.Connection, answer_id: int) -> list[int]:
    """Every row for the same question as ``answer_id``; raises `KeyError` when unknown."""
    row = conn.execute("SELECT label_norm FROM answer_memory WHERE id = ?", (answer_id,)).fetchone()
    if row is None:
        raise KeyError(answer_id)
    return [
        int(r[0])
        for r in conn.execute("SELECT id FROM answer_memory WHERE label_norm = ?", (row[0],))
    ]


def update(answer_id: int, answer: str) -> SavedAnswer:
    """Replace a saved answer's text (the Profile page's edit). Raises `KeyError`."""
    answer = (answer or "").strip()
    if not answer or len(answer) > MAX_ANSWER_CHARS:
        raise ValueError(f"An answer must be 1 to {MAX_ANSWER_CHARS} characters.")
    conn = _conn()
    with db.transaction(conn):
        # The Profile page shows one row per question: an edit answers it on every site.
        ids = _question_ids(conn, answer_id)
        now = _now()
        conn.executemany(
            "UPDATE answer_memory SET answer = ?, source = 'edited', updated_at = ? WHERE id = ?",
            [(answer, now, row_id) for row_id in ids],
        )
    saved = get(answer_id)
    assert saved is not None
    return saved


def delete(answer_id: int) -> None:
    """Forget the question ``answer_id`` belongs to, on every site."""
    conn = _conn()
    with db.transaction(conn):
        ids = _question_ids(conn, answer_id)
        conn.executemany("DELETE FROM answer_memory WHERE id = ?", [(row_id,) for row_id in ids])


def cleanup_profile_duplicates(conn: sqlite3.Connection | None = None) -> int:
    """Once per workspace: move rows a profile field answers out of answer memory.

    Earlier versions remembered corrections to profile questions ("Middle Name", "How
    did you hear about us?"), which the Profile page then showed twice. Each such row
    fills its profile field when that is blank, and is removed either way. The removed
    rows are written to ``backups/answer_memory-<stamp>.json`` first. Returns the
    number of rows removed.
    """
    conn = conn or _conn()
    if db.marker(conn, CLEANUP_MARKER):
        return 0
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM answer_memory ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    doomed = [(item, key) for item in map(_row, rows) if (key := profile_key(item.label))]
    if doomed:
        folder = Path(config.APPLICATIONS_PATH).parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        (folder / f"answer_memory-{stamp}.json").write_text(
            json.dumps([item.model_dump() for item, _key in doomed], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        for item, key in doomed:  # most recent first: its answer wins a blank field
            try:
                save_to_profile(key, item.answer)
            except Exception:  # noqa: BLE001 - the backup keeps the answer either way
                _log.warning("could not move saved answer %r into the profile", item.label)
    with db.transaction(conn):
        conn.executemany(
            "DELETE FROM answer_memory WHERE id = ?", [(item.id,) for item, _key in doomed]
        )
        db.set_marker(conn, CLEANUP_MARKER)
    return len(doomed)
