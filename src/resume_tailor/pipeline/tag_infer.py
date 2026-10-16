"""Inferred bullet skills: what a model reads into each bullet's text, cached per text.

The third layer of `content/bullet_tags.py`'s match tags. **Matching only**: these feed JD
matching, coverage and the gap report, never the fabrication whitelist,
`<permitted_skills>`, or the Skills-section pool — a model's guess at what a bullet
implies is not something the user claimed.

One batched call per uncached chunk of bullet texts, plain strings in and plain JSON out.
Cached in the workspace's `inferred_tags.json`, one table per model identity (the prompt
version and `config.fingerprint("extract", include_guidance=False)`), keyed by the bullet
text — so an edited bullet, a prompt change or a different model each infer afresh, and an
unchanged resume never calls the model again. The profile guidance is deliberately not part
of the key: this prompt never reads it, and keying on it split one cache between the Apply
screen (no guidance) and the tailor run (guidance), each pruning the other's entries.
Tables for the few most recent models are kept, so switching back costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from ..content import bullet_tags
from ..content.data import MasterResume
from ..infra import llm
from . import events

_log = logging.getLogger(__name__)

#: Bumped whenever `_SYSTEM` or the request shape changes — folded into every cache key.
_PROMPT_VERSION = 1

#: Bullets per model call; keeps a long resume inside small local models' context.
_CHUNK = 30

#: Skills kept per bullet, and the longest skill name accepted (in words).
_MAX_SKILLS = 8
_MAX_WORDS = 4

_FILE_NAME = "inferred_tags.json"

#: On-disk layout: ``{"version": 2, "models": {<model identity>: {<text key>: [skills]}}}``.
#: Version 1 was a flat ``{<key>: [skills]}`` map; it is migrated on read (`_lookup`).
_FORMAT_VERSION = 2

#: Model tables kept in the file, most recently used last.
_MAX_MODELS = 3

#: Where a version-1 file's flat entries sit until `_lookup` migrates them.
_LEGACY = "__v1__"

#: Serialises read-modify-write of the cache file between a background refresh and a run.
_LOCK = threading.Lock()

#: One lock per (cache file, model): concurrent `ensure` calls infer once — the later
#: callers wait, then find the entries the first one wrote.
_INFER_LOCKS: dict[tuple[str, str], threading.Lock] = {}

_SYSTEM = """\
You list the skills each resume bullet demonstrates, so the bullet can be matched to job \
postings.

For every bullet in <bullets>, return the skills, tools, technologies and methods it \
shows — both the ones it names and the ones its work clearly implies (a bullet about \
building dashboards in Tableau also shows "data visualization"). Prefer the names in \
<preferred_names> when one fits. Use short, standard names of one to four words, \
lowercase, no explanations. Leave out soft traits nobody would list as a skill \
("hard-working"). A bullet that shows no real skill gets an empty list.

Return one entry per bullet, keyed by the exact id you were given.
"""


class _BulletSkills(BaseModel):
    id: str
    skills: list[str] = Field(default_factory=list)


class _SkillTable(BaseModel):
    bullets: list[_BulletSkills] = Field(default_factory=list)


@dataclass
class Inference:
    """Inferred skills by bullet text, plus why any are missing."""

    skills: dict[str, list[str]]
    error: str | None = None


def cache_path() -> Path:
    """The active workspace's cache file (rebound per workspace like every data path)."""
    return config.DATA_DIR / _FILE_NAME


def _digest(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _model() -> str:
    """Identity of what would answer an inference now: prompt version + backend, no guidance."""
    return f"v{_PROMPT_VERSION}|{config.fingerprint('extract', include_guidance=False)}"


def _key(text: str) -> str:
    return _digest(text)


def _legacy_key(text: str) -> str:
    """A version-1 key: prompt version, the full extract fingerprint (guidance included)."""
    return _digest("\n".join([str(_PROMPT_VERSION), config.fingerprint("extract"), text]))


def _entries(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    return {
        k: [s for s in v if isinstance(s, str)]
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, list)
    }


Table = dict[str, dict[str, list[str]]]


def _read(path: Path) -> Table:
    """Model identity -> {text key: skills}; a version-1 file comes back under `_LEGACY`."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    if raw.get("version") == _FORMAT_VERSION and isinstance(raw.get("models"), dict):
        return {m: _entries(e) for m, e in raw["models"].items() if isinstance(m, str)}
    legacy = _entries(raw)
    return {_LEGACY: legacy} if legacy else {}


def _write(path: Path, table: Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    body = {"version": _FORMAT_VERSION, "models": table}
    tmp.write_text(json.dumps(body, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _lookup(table: Table, texts: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """`(known, migrated)` for `texts` under the current model. `migrated` is the subset
    recovered from a version-1 file (keyed under today's model and guidance) — no model
    call, but it still needs writing under the new key."""
    current = table.get(_model(), {})
    legacy = table.get(_LEGACY, {})
    known: dict[str, list[str]] = {}
    migrated: dict[str, list[str]] = {}
    for text in texts:
        if (hit := current.get(_key(text))) is not None:
            known[text] = hit
        elif legacy and (old := legacy.get(_legacy_key(text))) is not None:
            known[text] = migrated[text] = old
    return known, migrated


def _store(table: Table, entries: dict[str, list[str]], texts: list[str]) -> Table:
    """`table` with `entries` added under the current model, pruned to `texts` (the live
    bullets) in every model table, the current model moved last, at most `_MAX_MODELS`
    tables kept and any version-1 leftovers dropped."""
    model = _model()
    live = {_key(t) for t in texts}
    merged = {**table.get(model, {}), **{_key(t): s for t, s in entries.items()}}
    others = [(m, e) for m, e in table.items() if m not in (model, _LEGACY)]
    kept = [*others[max(0, len(others) - (_MAX_MODELS - 1)):], (model, merged)]
    return {m: {k: v for k, v in e.items() if k in live} for m, e in kept}


def _infer_lock(path: Path) -> threading.Lock:
    with _LOCK:
        return _INFER_LOCKS.setdefault((str(path), _model()), threading.Lock())


def _clean(skills: Iterable[str]) -> list[str]:
    kept: dict[str, None] = {}
    for raw in skills:
        skill = " ".join(raw.split()).lower().strip(" .,;:")
        if skill and len(skill.split()) <= _MAX_WORDS:
            kept.setdefault(skill)
    return list(kept)[:_MAX_SKILLS]


def infer(texts: list[str], preferred: Iterable[str] = ()) -> dict[str, list[str]]:
    """One model call: skills for each of `texts` (unique strings). Raises on failure."""
    if not texts:
        return {}
    ids = {f"b{i}": text for i, text in enumerate(texts, start=1)}
    bullets = "\n".join(f"<bullet id={bid!r}>{text}</bullet>" for bid, text in ids.items())
    names = ", ".join(sorted(set(preferred))) or "(none)"
    user = (
        f"<preferred_names>{names}</preferred_names>\n\n"
        f"<bullets>\n{bullets}\n</bullets>"
    )
    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=_SkillTable,
        output_config={"effort": config.effort_for("extract")},
    )
    table = response.parsed_output
    if table is None:
        raise RuntimeError(
            f"Model did not return parseable bullet skills (stop_reason={response.stop_reason!r})."
        )
    # Unknown ids are dropped; a bullet the model skipped is simply retried next time.
    return {ids[item.id]: _clean(item.skills) for item in table.bullets if item.id in ids}


def cached(resume: MasterResume) -> Inference:
    """What is already inferred for `resume`'s bullets — no model call. `skills` lacks
    every text still waiting for inference under the current model and prompt."""
    texts = list(dict.fromkeys(b.text for b in resume.all_bullets()))
    known, _ = _lookup(_read(cache_path()), texts)
    return Inference(skills=known)


def ensure(
    resume: MasterResume,
    *,
    preferred: Iterable[str] = (),
    on_event: events.ProgressCallback | None = None,
) -> Inference:
    """Inferred skills for every bullet of `resume`, calling the model only for texts not
    cached yet. Never raises: a failed call keeps whatever was cached and names the
    error, so a run continues on Extra skills + detection alone.

    Calls for the same cache file and model are serialised (`_infer_lock`), so runs that
    start together infer once and the rest read what the first one wrote.
    """
    path = cache_path()
    texts = list(dict.fromkeys(b.text for b in resume.all_bullets()))
    with _infer_lock(path):
        return _ensure_locked(path, texts, preferred, on_event)


def _ensure_locked(
    path: Path,
    texts: list[str],
    preferred: Iterable[str],
    on_event: events.ProgressCallback | None,
) -> Inference:
    with _LOCK:
        known, migrated = _lookup(_read(path), texts)
    todo = [t for t in texts if t not in known]
    error: str | None = None
    fresh: dict[str, list[str]] = {}
    if todo:
        events.emit(
            on_event,
            "infer",
            f"Detecting skills in {len(todo)} bullet(s)",
            bullets=len(todo),
            model=config.model_for("extract"),
        )
        preferred = list(preferred)
        try:
            for start in range(0, len(todo), _CHUNK):
                fresh.update(infer(todo[start : start + _CHUNK], preferred))
        except Exception as exc:  # noqa: BLE001 - inference is optional; never fail a run
            _log.warning("Skill inference failed", exc_info=True)
            error = f"Skill detection skipped ({exc})"
            events.emit(on_event, "infer", error)
    if fresh or migrated:
        with _LOCK:
            # Re-read: another model's refresh may have written since. `_store` prunes
            # removed bullets from every table, so edits never grow the file unbounded.
            _write(path, _store(_read(path), {**migrated, **fresh}, texts))
    skills = {t: s for t in texts if (s := fresh.get(t, known.get(t))) is not None}
    return Inference(skills=skills, error=error)


def prepare_run(
    resume: MasterResume, *, on_event: events.ProgressCallback | None = None
) -> Inference:
    """Run start: fill any missing inferences, then install this run's match-tag context
    (`bullet_tags.annotate`). Call before anything reads match tags or `known_terms`."""
    bullet_tags.clear()
    inference = ensure(resume, preferred=bullet_tags.known_terms(resume), on_event=on_event)
    bullet_tags.annotate(resume, inference.skills)
    return inference


def annotate_cached(resume: MasterResume) -> Inference:
    """Install the match-tag context from what is already inferred — no model call.

    For work that resumes a finished run in a fresh context (regenerating its expansion):
    under the run's own backend pins it reads the same cache entries the run used. A
    context that never annotates reads no inferred skills at all (`bullet_tags._current`).
    """
    inference = cached(resume)
    bullet_tags.annotate(resume, inference.skills)
    return inference
