"""Inferred bullet skills: what a model reads into each bullet's text, cached per text.

The third layer of `content/bullet_tags.py`'s match tags. **Matching only**: these feed JD
matching, coverage and the gap report, never the fabrication whitelist,
`<permitted_skills>`, or the Skills-section pool — a model's guess at what a bullet
implies is not something the user claimed.

One batched call per uncached chunk of bullet texts, plain strings in and plain JSON out.
Cached in the workspace's `inferred_tags.json`, keyed by the bullet text, the prompt
version and `config.fingerprint("extract")` — so an edited bullet, a prompt change or a
different model each infer afresh, and an unchanged resume never calls the model again.
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

#: Serialises read-modify-write of the cache file between a background refresh and a run.
_LOCK = threading.Lock()

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


def _key(text: str) -> str:
    payload = "\n".join([str(_PROMPT_VERSION), config.fingerprint("extract"), text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _read(path: Path) -> dict[str, list[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        k: [s for s in v if isinstance(s, str)]
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, list)
    }


def _write(path: Path, table: dict[str, list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(table, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


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
    table = _read(cache_path())
    texts = dict.fromkeys(b.text for b in resume.all_bullets())
    return Inference(skills={t: table[_key(t)] for t in texts if _key(t) in table})


def ensure(
    resume: MasterResume,
    *,
    preferred: Iterable[str] = (),
    on_event: events.ProgressCallback | None = None,
) -> Inference:
    """Inferred skills for every bullet of `resume`, calling the model only for texts not
    cached yet. Never raises: a failed call keeps whatever was cached and names the
    error, so a run continues on Extra skills + detection alone.
    """
    path = cache_path()
    texts = list(dict.fromkeys(b.text for b in resume.all_bullets()))
    with _LOCK:
        table = _read(path)
    todo = [t for t in texts if _key(t) not in table]
    error: str | None = None
    if todo:
        events.emit(
            on_event,
            "infer",
            f"Detecting skills in {len(todo)} bullet(s)",
            bullets=len(todo),
            model=config.model_for("extract"),
        )
        preferred = list(preferred)
        fresh: dict[str, list[str]] = {}
        try:
            for start in range(0, len(todo), _CHUNK):
                fresh.update(infer(todo[start : start + _CHUNK], preferred))
        except Exception as exc:  # noqa: BLE001 - inference is optional; never fail a run
            _log.warning("Skill inference failed", exc_info=True)
            error = f"Skill detection skipped ({exc})"
            events.emit(on_event, "infer", error)
        if fresh:
            with _LOCK:
                table = _read(path)
                table.update({_key(t): skills for t, skills in fresh.items()})
                # Keep only the current bullets under the current model, so edits and
                # model switches never let the file grow without bound.
                live = {_key(t) for t in texts}
                table = {k: v for k, v in table.items() if k in live}
                _write(path, table)
    skills = {t: table[_key(t)] for t in texts if _key(t) in table}
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
