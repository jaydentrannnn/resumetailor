"""Job-description parsing: raw JD text in, structured requirements out.

This is one of only two modules that talk to the API, and it exchanges plain text and
JSON only — nothing here knows that a `.docx` exists.

The output is schema-validated via `client.messages.parse()` rather than parsed out of
prose, so a malformed response is a Pydantic error at the boundary instead of a subtle
mismatch three stages later.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import config, events, llm

Importance = Literal["must_have", "nice_to_have"]
Kind = Literal["technical", "soft"]


class Keyword(BaseModel):
    """One skill or requirement drawn from the JD."""

    #: The JD's own wording, copied verbatim. This is the point of the whole exercise:
    #: mirroring the posting's exact phrasing is what moves keyword-match scoring, and
    #: it is what tools that paraphrase into their own vocabulary get wrong.
    phrase: str

    #: Normalised form, used to match against bullet tags in `rewrite.py`.
    canonical: str

    importance: Importance

    #: Whether this names a technology/method or a human skill. Soft must-haves are scored
    #: at `config.SOFT_SKILL_WEIGHT` rather than `MUST_HAVE_WEIGHT` — see the note there.
    #:
    #: Defaults to "technical", which is both the conservative reading (an unclassified
    #: requirement keeps full weight rather than being quietly discounted) and what keeps
    #: `*.requirements.json` files written before this field existed loading unchanged.
    kind: Kind = "technical"


class JobRequirements(BaseModel):
    """Everything the rewriter needs to know about a posting."""

    title: str
    seniority: Literal["intern", "entry", "mid", "senior", "lead"]
    keywords: list[Keyword] = Field(default_factory=list)

    #: Context that is not a keyword but should colour the rewrite — domain, industry,
    #: team shape, notable responsibilities.
    domain_notes: list[str] = Field(default_factory=list)

    def by_importance(self, importance: Importance) -> list[Keyword]:
        return [k for k in self.keywords if k.importance == importance]


_SYSTEM = """\
You extract structured hiring requirements from job descriptions.

Rules:
- Emit ONE entry per ATOMIC skill. A requirement naming several skills becomes several \
entries, never one combined entry. "Hands-on experience with vector databases and \
semantic search" is two entries, not one.
- `phrase` MUST be copied verbatim from the job description, character for character — \
but only the span that names the skill, not the whole sentence around it. For the example \
above the phrases are "vector databases" and "semantic search". Do not paraphrase, expand \
abbreviations, or fix the posting's capitalisation: this exact wording is later mirrored \
back into a resume, so accuracy matters more than tidiness.
- `canonical` is a SHORT lowercase tag naming that one skill, as it would appear in a \
skills taxonomy — normally one to three words. Expand abbreviations here instead \
("k8s" -> "kubernetes", "RAG" -> "rag"). It must NOT be a sentence, must not contain \
"and", "or", "+", parentheses, or a verb like "ship"/"build"/"measure". Prefer the \
singular, most standard name for the technology: "vector database", "semantic search", \
"reranking", "fastapi", "python", "llm", "prompt engineering", "latency optimization".
- If a `<known_tags>` list is supplied, it is the candidate's actual skill vocabulary. \
REUSE an existing tag verbatim as `canonical` whenever one genuinely means the same thing \
as the requirement — prefer "communication" over "communication skills", "data analysis" \
over "analytical skills". Only coin a new `canonical` when nothing in the list honestly \
fits. Do NOT stretch a tag to cover something it does not mean: a `canonical` that matches \
no known tag is useful signal that the candidate lacks that skill, and a forced match \
destroys it.
- Classify as `must_have` only what the posting frames as required, minimum, or \
essential. Anything framed as preferred, bonus, plus, or nice-to-have is `nice_to_have`.
- `kind` is "technical" for a technology, tool, language, platform, or concrete method, \
and "soft" for a human skill — communication, collaboration, organisation, attention to \
detail, curiosity, problem-solving disposition. When a requirement is genuinely both, or \
you are unsure, use "technical".
- Extract concrete skills, tools, technologies, and methodologies. Skip generic filler \
("team player", "fast-paced environment") unless the posting clearly treats it as a \
distinguishing requirement. Skip degree, education, visa, and location requirements \
entirely — they are not skills a resume bullet can demonstrate.
- `domain_notes` captures context worth reflecting in tone and emphasis: the industry, \
the product, the team's shape, the core responsibilities.
"""


#: Bumped whenever `_SYSTEM` or the shape of the user message changes. It is folded into
#: the cache key so a prompt edit invalidates every stored extraction automatically —
#: previously this relied on the operator remembering `--no-cache`, and a stale extraction
#: is invisible rather than merely wrong.
_PROMPT_VERSION = 2


def _slug(text: str, known_tags: list[str] | None = None) -> str:
    """Stable, filesystem-safe identifier for an extraction, used for the cache filename.

    The digest covers everything the extraction depends on, not just the posting: the tag
    vocabulary steers `canonical`, so re-tagging the master resume must produce a different
    key. Reusing an extraction canonicalised against a vocabulary that no longer exists
    would silently mis-score every bullet.

    The backend is part of the key too. Two models given the same posting produce different
    extractions, so reusing one under the other's name would misrank silently — and would
    make comparing backends impossible, since the second run would just replay the first.

    The leading words come from the JD alone, so the filename stays recognisable.
    """
    payload = "\n".join(
        [
            str(_PROMPT_VERSION),
            config.fingerprint("extract"),
            text,
            *sorted(known_tags or []),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]
    words = re.findall(r"[a-z0-9]+", text[:120].lower())[:4]
    return "-".join([*words, digest]) if words else digest


def _build_user_message(jd_text: str, known_tags: list[str] | None) -> str:
    """Assemble the extraction request.

    The tag vocabulary is passed as plain strings rather than a `MasterResume`: this module
    imports only `config`, and keeping `data` out of it preserves the dependency direction
    (the JD half of the pipeline never needs to know the resume's shape).
    """
    parts = [f"<job_description>\n{jd_text}\n</job_description>"]
    if known_tags:
        vocabulary = ", ".join(sorted(known_tags))
        parts.append(f"<known_tags>\n{vocabulary}\n</known_tags>")
    return "\n\n".join(parts)


def extract(
    jd_text: str,
    *,
    known_tags: list[str] | None = None,
    use_cache: bool = True,
    on_event: events.ProgressCallback | None = None,
) -> JobRequirements:
    """Extract structured requirements from job-description text.

    `known_tags` is the candidate's actual tag vocabulary. Without it the model coins
    `canonical` values in a vacuum and reliably misses — it emitted "communication skills"
    and "analytical skills" against a resume tagged `communication` and `data analysis`,
    taking must-have coverage to 2/7 on a posting the resume genuinely matched. Supplying
    the vocabulary lets the model do the synonym judgement, which is the part `TAG_ALIASES`
    cannot generalise: that table was hand-tuned for retrieval vocabulary and a
    different-domain posting re-opens the same gap.

    Results are cached to `<CACHE_DIR>/<slug>.requirements.json`. The fit loop can re-run
    the rewrite stage several times per invocation, and none of those retries should re-pay
    for an extraction whose input has not changed. The cache directory is deliberately not
    the run's output directory: the web UI gives every run its own output folder, and a
    per-run cache would never be hit.
    """
    jd_text = jd_text.strip()
    if not jd_text:
        raise ValueError("Job description is empty.")

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = config.CACHE_DIR / f"{_slug(jd_text, known_tags)}.requirements.json"

    if use_cache and cache_path.exists():
        events.emit(on_event, "extract", "Reusing cached job-description analysis", cached=True)
        return JobRequirements.model_validate_json(cache_path.read_text(encoding="utf-8"))

    events.emit(
        on_event,
        "extract",
        "Reading the job description",
        cached=False,
        model=config.model_for("extract"),
    )
    client = llm.client_for("extract")
    response = client.messages.parse(
        model=config.model_for("extract"),
        max_tokens=config.max_tokens_for("extract"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_user_message(jd_text, known_tags)}],
        output_format=JobRequirements,
        # The SDK merges `format` into `output_config`, so passing both is safe. Ignored
        # on the OpenAI-compatible path, which has no portable reasoning control.
        output_config={"effort": config.effort_for("extract")},
    )

    requirements = response.parsed_output
    if requirements is None:
        raise RuntimeError(
            f"Model did not return parseable requirements (stop_reason="
            f"{response.stop_reason!r}). Re-run, or inspect the JD for unusual content."
        )

    # Canonicalise through the same alias table the resume tags use, so the two sides of
    # the match are guaranteed to speak the same vocabulary.
    for kw in requirements.keywords:
        kw.canonical = config.canonical_tag(kw.canonical)

    cache_path.write_text(
        json.dumps(requirements.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    events.emit(
        on_event,
        "extract",
        f"Found {len(requirements.keywords)} keyword(s) for {requirements.title}",
        keywords=len(requirements.keywords),
        title=requirements.title,
    )
    return requirements


def extract_from_file(
    path: Path,
    *,
    known_tags: list[str] | None = None,
    use_cache: bool = True,
) -> JobRequirements:
    """Extract requirements from a JD stored on disk."""
    if not path.exists():
        raise FileNotFoundError(f"Job description not found: {path}")
    return extract(
        path.read_text(encoding="utf-8"), known_tags=known_tags, use_cache=use_cache
    )


def verify_verbatim(requirements: JobRequirements, jd_text: str) -> list[str]:
    """Return phrases that do not appear verbatim in the source JD.

    The verbatim guarantee is the feature, so it is checked rather than assumed. An empty
    list means every extracted phrase really is the posting's own wording.
    """
    haystack = " ".join(jd_text.lower().split())
    return [
        kw.phrase
        for kw in requirements.keywords
        if " ".join(kw.phrase.lower().split()) not in haystack
    ]
