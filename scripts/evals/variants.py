"""Eval-only pipeline variants, switched per task (context variable) or per process
(environment), never by editing production code.

* `CLAUSE`: one extra rule in `rewrite_prompts._system()`, so it reaches every call
  that prompt serves (first draft, factual retry, widow repair, merge), exactly as a
  production edit would.
* `gaps()`: cover-letter gap bridges (experiment 4d). Up to two unmet must-haves go to
  the model as `<unmet_requirements>` before the posting, `GAP_RULE` joins the system
  prompt's rules, and the claim guard lets a gap term through only in a sentence with a
  `GAP_CUE` ("not yet", "eager to learn"), so an honest bridge survives and a claim does
  not.

In-process arms (`arms.run` threads) use `clause()`; an end-to-end worker process sets
`CLAUSE_ENV` before `install()`. (The cosmetic-polish switch went with the polish:
`stages.cosmetic_polish` replays it on frozen drafts.)
"""

from __future__ import annotations

import contextvars
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

#: The narrow anti-invention clause under test (experiment E2).
CLAUSE = (
    "- Do not add specifics the bullet never states (audience, frequency, setting, error "
    "types, scope), even plausible ones.\n"
)
CLAUSE_ENV = "RT_EVAL_CLAUSE"
#: Every `_system()` variant ends with this line; the clause goes just above it.
_RETURN_MARKER = "Return one entry per input item"

_CLAUSE_ON: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "eval_clause", default=None)
_installed = False


def with_clause(system: str) -> str:
    """`system` with `CLAUSE` added as the last rule, before the return shape."""
    i = system.rfind(_RETURN_MARKER)
    if i < 0:
        return system.rstrip("\n") + "\n" + CLAUSE
    head = system[:i].rstrip("\n")
    return f"{head}\n{CLAUSE}\n{system[i:]}"


def _clause_active() -> bool:
    value = _CLAUSE_ON.get()
    return value if value is not None else os.environ.get(CLAUSE_ENV) == "1"


def install() -> None:
    """Wrap the prompt seam once per process; with the clause off it is a no-op."""
    global _installed
    if _installed:
        return
    from resume_tailor.pipeline import rewrite_prompts

    original_system = rewrite_prompts._system

    def system() -> str:
        text = original_system()
        return with_clause(text) if _clause_active() else text

    rewrite_prompts._system = system
    _installed = True


@contextmanager
def clause(on: bool = True) -> Iterator[None]:
    install()
    token = _CLAUSE_ON.set(on)
    try:
        yield
    finally:
        _CLAUSE_ON.reset(token)


# -- cover-letter gap bridges (experiment 4d) ---------------------------------------------

GAP_RULE = (
    "- <unmet_requirements>, when present, lists required skills the resume does not show. "
    "You may acknowledge at most one or two of them honestly, as something you have not "
    "done yet, and bridge from related experience on the tailored resume. Never claim "
    "them, and never imply experience with them.\n"
)
#: Wording that makes a sentence an honest gap rather than a claim.
GAP_CUE = re.compile(
    r"\b(?:not yet|haven't|have not|hasn't|has not|no (?:direct |professional |hands-on )?"
    r"experience|new to|eager to learn|learning|to learn|look forward to|ramp(?:ing)? up|"
    r"picking up|studying)\b",
    re.IGNORECASE,
)
#: The cover prompt's return-shape line; the rule goes just above it.
_COVER_RETURN_MARKER = "Return a JSON object"

_GAPS: contextvars.ContextVar[tuple[str, ...] | None] = contextvars.ContextVar(
    "eval_gaps", default=None)
_gaps_installed = False


def gap_block(gaps: Sequence[str]) -> str:
    lines = "".join(f"- {g}\n" for g in gaps)
    return f"<unmet_requirements>\n{lines}</unmet_requirements>\n\n"


def _is_gap_term(term: str, gaps: Sequence[str]) -> bool:
    term = term.lower()
    return any(term in gap.lower() or gap.lower() in term for gap in gaps)


def install_gaps() -> None:
    """Wrap the cover letter's system prompt, user message and claim check once per
    process; each wrapper is a no-op unless the task set `gaps()`."""
    global _gaps_installed
    if _gaps_installed:
        return
    from resume_tailor.pipeline import coverletter

    original_system = coverletter._system
    original_user = coverletter._user_message
    original_check = coverletter._check_fabrication

    def system() -> str:
        text = original_system()
        if not _GAPS.get():
            return text
        i = text.rfind(_COVER_RETURN_MARKER)
        return text + GAP_RULE if i < 0 else text[:i] + GAP_RULE + "\n" + text[i:]

    def user_message(**kwargs) -> str:
        text = original_user(**kwargs)
        gaps = _GAPS.get()
        if not gaps:
            return text
        frame = coverletter._POSTING_FRAME
        return text.replace(frame, gap_block(gaps) + frame, 1)

    def check(sources, sentence: str) -> list[str]:
        offenders = original_check(sources, sentence)
        gaps = _GAPS.get()
        if gaps and GAP_CUE.search(sentence):
            offenders = [o for o in offenders if not _is_gap_term(o, gaps)]
        return offenders

    coverletter._system = system
    coverletter._user_message = user_message
    coverletter._check_fabrication = check
    _gaps_installed = True


@contextmanager
def gaps(unmet: Sequence[str]) -> Iterator[None]:
    install_gaps()
    token = _GAPS.set(tuple(unmet))
    try:
        yield
    finally:
        _GAPS.reset(token)
