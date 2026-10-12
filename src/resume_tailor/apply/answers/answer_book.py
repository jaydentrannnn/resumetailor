"""The Answer book: every answer a fill may reuse, in one table (`answer_memory`'s).

Sources, as the Profile page badges them:

- ``correction`` / ``edited`` ("You"): a review correction, or an edit on the Profile page.
- ``page`` ("From page"): what the applicant typed into a field the fill left for them
  (`funnel.answer_harvest`).
- ``custom`` ("Custom"): a question and answer added on the Profile page. The profile's
  old ``custom_answers`` are moved here once (`import_legacy`).
- ``ai`` ("AI"): a dropdown or radio pick the autofill model made. Its ``options_digest``
  is the resolver's choice key (question, options, model and profile), so a pick is only
  reused for the very same question and profile; the old ``resolver-choices.json`` is
  imported once.

Kind ``type`` rows are question types the classifier learned (`learn_type`): the next
form asking the same question with the same options is keyed without a model call.
Only low-risk types are learned; eligibility, sponsorship, legal and self-identification
types are always the classifier's (and its rules') call, never a stored row.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_tailor import config
from resume_tailor.apply.answers import answer_memory
from resume_tailor.storage import db

_log = logging.getLogger(__name__)

IMPORT_MARKER = "answer_book_import_v1"
#: Question types a classifier result may be remembered for (see the module docstring).
LEARNABLE_TYPES = frozenset({
    "over_18", "willing_to_relocate", "currently_enrolled", "degree_by",
    "returning_to_school", "gpa_at_least", "located_or_relocate", "has_prior_internship",
    "degree_level", "highest_education_obtained", "major",
})  # fmt: skip


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def options_digest(options: Iterable[str]) -> str:
    """A question's options, order and case aside, as a short key."""
    joined = "\n".join(sorted(str(option).strip().casefold() for option in options))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# -- one-off import of the older stores ---------------------------------------------------


def import_legacy(conn: sqlite3.Connection | None = None) -> None:
    """Once per workspace: bring the model's cached picks and the profile's custom
    answers into the book. The profile's custom answers are backed up, then cleared."""
    conn = conn or answer_memory._conn()
    if db.marker(conn, IMPORT_MARKER):
        return
    try:
        _import_ai_choices(conn)
        _import_custom_answers()
    except Exception:  # noqa: BLE001 - a failed import must never stop a fill
        _log.warning("could not import older saved answers", exc_info=True)
        return
    with db.transaction(conn):
        db.set_marker(conn, IMPORT_MARKER)


def _import_ai_choices(conn: sqlite3.Connection) -> None:
    from resume_tailor.apply.answers import hybrid_resolver  # noqa: PLC0415

    entries = {
        key: {**entry, "digest": f"{entry.get('version', '')}:{entry.get('digest', '')}"}
        for key, entry in hybrid_resolver._read_choices().items()
        if isinstance(entry, dict) and entry.get("action") and entry.get("value")
    }
    _save_ai(conn, entries, ignore_existing=True)


def _import_custom_answers() -> None:
    from resume_tailor.apply.answers import profile as profile_mod  # noqa: PLC0415

    current, _seeded = profile_mod.load_profile()
    answers = {q: a for q, a in current.custom_answers.items() if q.strip() and a.strip()}
    if not current.custom_answers:
        return
    folder = Path(config.APPLICATIONS_PATH).parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (folder / f"custom_answers-{stamp}.json").write_text(
        json.dumps(current.custom_answers, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for question, text in answers.items():
        key = answer_memory.profile_key(question)
        if key:
            answer_memory.save_to_profile(key, text)
        else:
            answer_memory.remember(question, text, source="custom")
    latest, _seeded = profile_mod.load_profile()  # save_to_profile may have changed it
    profile_mod.save_profile(latest.model_copy(update={"custom_answers": {}}))


def custom_answers() -> dict[str, str]:
    """The book's custom answers, question -> answer (what the model is shown)."""
    conn = answer_memory._conn()
    import_legacy(conn)
    rows = conn.execute(
        "SELECT label, answer FROM answer_memory WHERE kind = 'answer' AND source = 'custom' "
        "ORDER BY id"
    ).fetchall()
    return {str(label): str(text) for label, text in rows}


# -- the autofill model's picks -----------------------------------------------------------


def ai_choices(keys: Iterable[str]) -> dict[str, dict[str, str]]:
    """The saved picks for these resolver choice keys: key -> action, value and label."""
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    conn = answer_memory._conn()
    import_legacy(conn)
    marks = ",".join("?" * len(wanted))
    rows = conn.execute(
        "SELECT options_digest, action, answer, label FROM answer_memory "
        f"WHERE kind = 'answer' AND options_digest IN ({marks})",
        wanted,
    ).fetchall()
    return {
        str(key): {"action": str(action), "value": str(value), "label": str(label)}
        for key, action, value, label in rows
    }


def save_ai_choices(entries: dict[str, dict[str, Any]]) -> None:
    """Remember the model's picks: choice key -> action, value, label, options, digest."""
    if entries:
        with contextlib.suppress(sqlite3.Error):
            _save_ai(answer_memory._conn(), entries, ignore_existing=False)


def _save_ai(
    conn: sqlite3.Connection, entries: dict[str, dict[str, Any]], *, ignore_existing: bool
) -> None:
    now = _now()
    verb = "INSERT OR IGNORE" if ignore_existing else "INSERT OR REPLACE"
    rows = []
    for key, entry in entries.items():
        label = str(entry.get("label") or "")[:200]
        rows.append((
            answer_memory.normalize_label(label) or key, key, label, str(entry["value"]),
            str(entry["action"]), json.dumps([str(o) for o in entry.get("options") or []][:50]),
            str(entry.get("digest") or ""), now, now,
        ))
    with db.transaction(conn):
        conn.executemany(
            f"{verb} INTO answer_memory(kind, label_norm, ats, options_digest, label, answer, "
            "action, options, profile_digest, source, created_at, updated_at) "
            "VALUES ('answer', ?, '', ?, ?, ?, ?, ?, ?, 'ai', ?, ?)",
            rows,
        )


def ai_digest(profile_digest: str) -> str:
    """What an AI row's ``profile_digest`` holds: the resolver prompt version and profile."""
    from resume_tailor.apply.answers import hybrid_resolver  # noqa: PLC0415

    return f"{hybrid_resolver._RESOLVER_PROMPT_VERSION}:{profile_digest}"


def stale_ai_ids(conn: sqlite3.Connection) -> set[int]:
    """AI picks made for an older profile or prompt: never reused, so not listed."""
    from resume_tailor.apply.answers import hybrid_resolver  # noqa: PLC0415

    import_legacy(conn)
    rows = conn.execute(
        "SELECT id, profile_digest FROM answer_memory WHERE source = 'ai' AND kind = 'answer'"
    ).fetchall()
    if not rows:
        return set()
    current = ai_digest(hybrid_resolver.current_digest())
    return {int(row_id) for row_id, digest in rows if digest != current}


# -- learned question types ---------------------------------------------------------------


def learned_type(text: str, options: Iterable[str]) -> str | None:
    """The type learned for this question and options, or None."""
    norm = answer_memory.normalize_label(text)
    if not norm:
        return None
    row = answer_memory._conn().execute(
        "SELECT id, canonical_key FROM answer_memory WHERE kind = 'type' AND label_norm = ? "
        "AND options_digest = ?",
        (norm, options_digest(options)),
    ).fetchone()
    if row is None or row[1] not in LEARNABLE_TYPES:
        return None
    conn = answer_memory._conn()
    with db.transaction(conn):
        conn.execute("UPDATE answer_memory SET uses = uses + 1 WHERE id = ?", (row[0],))
    return str(row[1])


def learn_type(text: str, options: Iterable[str], key: str, meaning: str) -> bool:
    """Remember that this question asks for ``key``; False when it may not be learned."""
    options = [str(option) for option in options]
    norm = answer_memory.normalize_label(text)
    if key not in LEARNABLE_TYPES or not norm or answer_memory.is_sensitive(text):
        return False
    now = _now()
    conn = answer_memory._conn()
    with db.transaction(conn):
        conn.execute(
            "INSERT OR REPLACE INTO answer_memory(kind, label_norm, ats, options_digest, label, "
            "answer, canonical_key, options, source, created_at, updated_at) "
            "VALUES ('type', ?, '', ?, ?, ?, ?, ?, 'ai', ?, ?)",
            (norm, options_digest(options), text.strip()[:500], meaning, key,
             json.dumps(options[:50]), now, now),
        )
    return True


def forget_type_cache(text: str, options: list[str]) -> None:
    """Drop the classifier's own cache for a forgotten type, so it is asked afresh."""
    from resume_tailor.apply.answers import answer, questions  # noqa: PLC0415

    question = questions.Question(text, kind="choice", options=tuple(options))
    answer._classify_cache_path(question).unlink(missing_ok=True)
