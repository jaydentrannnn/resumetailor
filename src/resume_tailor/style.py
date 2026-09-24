"""Per-run writing-style overrides for LLM system prompts.

The rewrite, expand, and cover stages split their system prompts into a locked core
(fabrication, numbers, ids, length cliff) and an editable style block. This module holds the
default style text, the per-run active override, and a digest for cache keys — module state
rather than a threaded parameter, for the same reason ``config._ACTIVE`` is module state.

One punctuation trap, specific to ``DEFAULT_COVER_STYLE``: a model mimics the punctuation of
its own instructions, so a style block written with em dashes produces output full of them.
The cover style is deliberately written without a single long dash, and must stay that way.
The rewrite and expand defaults above it predate that rule and are left as they are, since
their output is resume bullets rather than prose.
"""

from __future__ import annotations

import hashlib

#: Default style block for resume bullet rewriting — editable portions of ``rewrite._SYSTEM``.
DEFAULT_REWRITE_STYLE = """\
- Mirror the posting's wording only where it names something the bullet already does, and \
only when the two genuinely mean the same thing: if the bullet says "fuzzy matching" and \
the posting says "approximate string matching", prefer the posting's.
- Soft skills are shown by the work, never named. Do not open a bullet by asserting \
communication, collaboration, problem-solving, organisation, attention to detail, or \
teamwork. "Applied problem-solving skills to a 45% accuracy bottleneck" and "Utilized \
verbal communication skills to facilitate three weekly labs" both waste their strongest \
words on a claim the rest of the sentence already proves — write "Diagnosed a 45% accuracy \
bottleneck" and "Facilitated three weekly labs" instead.
- When the bullet already shows the candidate driving, owning, or leading something — not \
just contributing to it — say so with the verb that names it plainly ("led", "drove", \
"spearheaded", "owned") rather than a flatter one ("worked on", "helped with", \
"contributed to"). If nothing in the bullet supports it, the plain accurate verb wins — an \
honest "built" beats a stretched "led".
- Foreground the accomplishment. When the bullet already states a result, scale, or \
comparison, lead with what changed rather than burying it after the mechanism that \
produced it — a reader weighs outcome over process. This is about ordering and emphasis, \
not new content.
- Write like a person. The bullet should read as a plain description of what was done, \
not as a checklist of the posting's vocabulary stitched into a sentence.
- Keep the strong-verb-first resume register. No first person, no full stops mid-bullet \
where a semicolon reads better, no filler.
- Vary the opening verb. You are given every bullet at once, so treat them as one \
document: no two may open with the same verb, and no more than two may open with \
near-synonyms — "designed", "engineered", "architected" and "built" are one verb wearing \
four hats. Reach for the verb that names what the work actually was.
- Say each thing once across the whole set. Two bullets making the same claim in different \
words waste a line and read as padding; distinguish them by what each one actually did.
"""

#: Default style block for application-form experience expansion.
DEFAULT_EXPAND_STYLE = """\
- Mirror the posting's wording only where it names something the source already does, and \
only when the two genuinely mean the same thing. A keyword the source cannot honestly \
claim is meant to go unused.
- Soft skills are shown by the work, never named. Do not open a bullet by asserting \
communication, collaboration, problem-solving, organisation, attention to detail, or \
teamwork.
- Write bullets, not paragraphs. One accomplishment per bullet, strong verb first. No \
first person. No leading bullet glyphs (•, -, *) — return plain text only.
- Vary the opening verb within each entry. No two bullets in the same entry may open with \
the same verb, and no more than two may open with near-synonyms.
- Aim for 5–8 bullets per entry when the source material supports it; fewer is fine when \
the entry is thin.
"""

#: Default style block for the cover letter's body paragraphs.
#:
#: Written with no em dash or en dash anywhere, on purpose — see this module's docstring.
#: The "Candidate positioning" section is the one place persona facts live that the resume
#: schema has no field for (what the candidate goes by, what roles they are targeting, which
#: strengths to lead with). Everything else the letter says about the candidate is generated
#: from ``master_resume.json`` at run time and never restated here.
DEFAULT_COVER_STYLE = """\
Voice
- Lead with what was done, not how it felt. Reach for a number, percentage, or concrete \
outcome before any general claim.
- Plain, direct sentences. Use technical vocabulary naturally, without over-explaining it \
and without reaching for jargon that adds nothing.
- Confident and matter-of-fact. No hedging such as "I believe" or "I think I could", and no \
inflated enthusiasm.
- Do not claim unearned traits such as passionate, hardworking, or team player. If a trait \
matters, prove it with a result.
- Mostly short declarative sentences, with one longer sentence per paragraph for rhythm. \
Never more than one subordinate clause deep.
- Frame everything around what the employer needs rather than what the candidate wants.

Structure, four paragraphs, about 350 words
- Opening: name the role and open on something concrete. Never "I am writing to apply for".
- Body 1: connect the single most relevant experience to the employer's top stated need.
- Body 2: one quantified accomplishment addressing a second need, in two or three tight \
sentences.
- Close: a confident, specific call to action. Not "I hope to hear from you".
- Select two or three experiences in total. Never recap the whole resume.
- Mirror the posting's own verbs and vocabulary only where the source honestly supports it.

Candidate positioning
- Derive the candidate's focus from the tailored resume and the posting. Do not invent a \
specialty, a career goal, or a name the resume does not state.
"""

_STAGES = ("rewrite", "expand", "cover")
_DEFAULTS = {
    "rewrite": DEFAULT_REWRITE_STYLE,
    "expand": DEFAULT_EXPAND_STYLE,
    "cover": DEFAULT_COVER_STYLE,
}
#: ``None`` means use the shipped default assembly; a string is a user override.
_ACTIVE: dict[str, str | None] = {stage: None for stage in _STAGES}


def activate(
    *,
    rewrite: str | None = None,
    expand: str | None = None,
    cover: str | None = None,
) -> None:
    """Bind style overrides for one tailoring run. Clears any prior activation."""
    _ACTIVE["rewrite"] = rewrite
    _ACTIVE["expand"] = expand
    _ACTIVE["cover"] = cover


def is_overridden(stage: str) -> bool:
    """Return True when ``stage`` carries a user override rather than the shipped default."""
    if stage not in _STAGES:
        raise ValueError(f"Unknown style stage {stage!r}. Expected one of {_STAGES}.")
    return _ACTIVE[stage] is not None


def active(stage: str) -> str:
    """Return the active style block for ``stage`` — override or shipped default."""
    if stage not in _STAGES:
        raise ValueError(f"Unknown style stage {stage!r}. Expected one of {_STAGES}.")
    override = _ACTIVE[stage]
    return override if override is not None else _DEFAULTS[stage]


def digest(stage: str) -> str:
    """Short hash of the active style text, folded into cached stage keys."""
    payload = active(stage)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
