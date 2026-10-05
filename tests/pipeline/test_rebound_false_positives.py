"""Rebound-number check: faithful rewrites that real runs wrongly rejected, plus true rebinds."""

import pytest

from resume_tailor.content.data import Bullet
from resume_tailor.pipeline import bullet_checks

_SERVING = (
    "Wired a query path through a Python 3.11 Lambda function calling a hosted model, "
    "with a Streamlit frontend on EC2 so users could ask natural-language questions."
)
_STACK = (
    "Delivered the full stack: a FastAPI backend streaming live events over SSE into a "
    "Next.js 15 UI with real-time agent traces, deployed via Docker Compose."
)
_CHATBOT = (
    "Developed support chatbots via a TypeScript SDK to automate routine inquiries, "
    "serving about 1000 customers daily and increasing ARR by 12%."
)


def _rebound(source: str, rewrite: str) -> list[str]:
    return bullet_checks.rebound_numbers([Bullet(id="b", text=source, tags=["python"])], rewrite)


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        # EC2 names a machine; it is not a count of natural-language anything.
        (_SERVING, "Wired a Python 3.11 Lambda query path with a Streamlit frontend on EC2 "
                   "for natural-language questions."),
        # "Next.js 15" is a version, not fifteen frontends.
        (_STACK, "Delivered a FastAPI backend and Next.js 15 frontend, streaming live events "
                 "over SSE, deployed via Docker Compose."),
        # The figure measures ARR wherever the rewrite puts it, whatever the verb.
        (_CHATBOT, "Developed support chatbots via a TypeScript SDK, serving about 1000 "
                   "customers daily and lifting ARR by 12%."),
        (_CHATBOT, "Developed support chatbots via a TypeScript SDK that raised ARR 12%, "
                   "serving about 1000 customers daily."),
    ],
)
def test_faithful_rewrites_are_not_rebinds(source, rewrite):
    assert _rebound(source, rewrite) == []


@pytest.mark.parametrize(
    ("source", "rewrite", "claim"),
    [
        ("Mentored 40 engineers across two teams.", "Mentored a team, saving 40 hours weekly.",
         "40 hours"),
        ("Tutored over 130 students/week.", "Tutored 130 students/semester.",
         "130 students/semester"),
        (_CHATBOT, "Developed support chatbots via a TypeScript SDK serving 1000 customers "
                   "daily and cutting costs by 12%.", "12 costs"),
    ],
)
def test_true_rebinds_are_still_flagged(source, rewrite, claim):
    assert _rebound(source, rewrite) == [claim]


def test_a_count_after_the_opening_verb_is_not_a_version():
    """'Led 40 engineers' is a count even though 'Led' is capitalised."""
    assert _rebound("Led 40 engineers on a migration.", "Led 40 hours of migration work.") == [
        "40 hours"
    ]
