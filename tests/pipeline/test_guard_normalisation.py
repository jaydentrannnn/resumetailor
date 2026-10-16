"""Narrow guard equivalences found by replaying real rejected drafts (2026-10 retry probe).

Each faithful restatement below once sent a draft to the factual retry. Every one is
paired with real alterations that must still be rejected, and with existing rejections
(versions, ranges, units, lower bounds, dates, fractions) that the change must not loosen.
"""

import pytest

from resume_tailor.content.data import Bullet
from resume_tailor.pipeline import bullet_checks, fabrication

_LLM = (
    "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider text-to-SQL "
    "examples using Hugging Face TRL's GRPOTrainer and colocated vLLM rollouts (16K-token "
    "context) on four A30/L40S GPUs."
)
_AGENT = (
    "Built a LangGraph research agent that plans, fans out parallel tool calls across web "
    "search, arXiv, PDF, and E2B-sandboxed code tools, and produces cited reports."
)
_STACK = (
    "Built the React 19 + TypeScript frontend over a FastAPI and SQLite backend, covered by "
    "about 2,700 pytest and 350 Vitest tests."
)
_LA = (
    "Grouped students hitting the same bug into shared debugging sessions with two fellow "
    "learning assistants, letting a team of three support 130+ students/week across three "
    "weekly labs."
)
_SCHED = (
    "Built a piecewise reward-weight scheduler shifting emphasis to the execution reward "
    "(0.10 to 0.70), with exact-match evaluation every 512 steps logged to Weights & Biases."
)
_MENTOR = (
    "Mentored students across 18 topics, including modules, namespaces, classes, objects, "
    "and asymptotic analysis."
)
_SEARCH = (
    "Built typo normalization and hybrid scoring so misspelled street queries still match, "
    "reaching 91.3% top-3 accuracy on a held-out test set."
)


def _offenders(source: str, rewrite: str, *tags: str) -> list[str]:
    bullet = Bullet(id="b", text=source, tags=list(tags))
    return bullet_checks.guard_offenders([bullet], rewrite, preserve_numbers=True)


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        # A hyphenated count and its spaced form state the same thing.
        (_LLM, "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider "
               "text-to-SQL examples using Hugging Face TRL's GRPOTrainer and colocated vLLM "
               "rollouts with 16K tokens of context on four A30/L40S GPUs."),
        (_LLM, "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider "
               "text-to-SQL examples using Hugging Face TRL's GRPOTrainer and colocated vLLM "
               "rollouts (16K context) on four A30/L40S GPUs."),
        (_AGENT, "Built a LangGraph research agent that plans, fans out parallel tool calls "
                 "across web search, arXiv, PDF, and E2B sandboxes, and produces cited reports."),
        # A version inside a slash list is still stated.
        (_STACK, "Built the React 19/TypeScript frontend over a FastAPI and SQLite backend, "
                 "covered by about 2,700 pytest and 350 Vitest tests."),
        # An identifier list may be spelled out.
        (_LLM, "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider "
               "text-to-SQL examples using Hugging Face TRL's GRPOTrainer and colocated vLLM "
               "rollouts (16K-token context) on four A30 and L40S GPUs."),
        # Numerals for number words, and the reverse.
        (_LA, "Grouped students hitting the same bug into shared debugging sessions with two "
              "fellow learning assistants, letting a team of 3 support 130+ students/week "
              "across 3 weekly labs."),
        ("Led 4 interns through onboarding.", "Led four interns through onboarding."),
        # "W&B" abbreviates "Weights & Biases".
        (_SCHED, "Built a piecewise reward-weight scheduler shifting emphasis to the execution "
                 "reward (0.10 to 0.70), with exact-match evaluation every 512 steps logged to W&B."),
        # An inserted modifier does not move the count to another subject.
        (_MENTOR, "Mentored students across 18 core computer science topics, including "
                  "modules, namespaces, classes, objects, and asymptotic analysis."),
        (_MENTOR, "Mentored students across 18 fundamental topics, including modules, "
                  "namespaces, classes, objects, and asymptotic analysis."),
        # The outcome verb changing tense or wording does not move the percentage.
        (_SEARCH, "Built typo normalization and hybrid scoring so misspelled street queries "
                  "still match, achieving 91.3% top-3 accuracy on a held-out test set."),
        (_SEARCH, "Built typo normalization and hybrid scoring so misspelled street queries "
                  "still match, which reached 91.3% top-3 accuracy on a held-out test set."),
    ],
)
def test_faithful_restatements_pass(source, rewrite):
    assert _offenders(source, rewrite) == []


@pytest.mark.parametrize(
    ("source", "rewrite", "expected"),
    [
        # The unit changed: same figure, different subject.
        (_LLM, "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider "
               "text-to-SQL examples using Hugging Face TRL's GRPOTrainer and colocated vLLM "
               "rollouts for 16K users on four A30/L40S GPUs.", "rebound:16k users"),
        # Dropped outright.
        (_AGENT, "Built a LangGraph research agent that plans, fans out parallel tool calls "
                 "across web search, arXiv, PDF, and sandboxed code tools, and produces cited "
                 "reports.", "missing_number:E2B-sandboxed"),
        (_LLM, "Fine-tuned Qwen and DeepSeek LLMs with two teammates on 9,000+ Spider "
               "text-to-SQL examples using Hugging Face TRL's GRPOTrainer and colocated vLLM "
               "rollouts (16K-token context) on four A30 GPUs.", "missing_number:A30/L40S"),
        (_STACK, "Built the React/TypeScript frontend over a FastAPI and SQLite backend, "
                 "covered by about 2,700 pytest and 350 Vitest tests.", "missing_number:19"),
        # A different value, whatever the spelling.
        (_LA, "Grouped students hitting the same bug into shared debugging sessions with two "
              "fellow learning assistants, letting a team of 4 support 130+ students/week "
              "across three weekly labs.", "4"),
        ("Led 4 interns through onboarding.", "Led five interns through onboarding.",
         "missing_number:4"),
        ("Led four interns through onboarding.", "Led 40 interns through onboarding.", "40"),
        # An ampersand abbreviation the source cannot spell.
        ("Owned budget reviews for the platform team.", "Owned P&L reviews for the platform team.",
         "P"),
        ("Logged runs to Weights for review.", "Logged runs to W&B for review.", "W"),
        # A modifier does not excuse a different subject.
        (_MENTOR, "Mentored 18 core students on namespaces, classes, objects, and asymptotic "
                  "analysis.", "rebound:18 core"),
        # A model variant is not restated by the base name.
        ("Evaluated o3-mini against the baseline.", "Evaluated o3 against the baseline.",
         "missing_number:o3-mini"),
        # "one of" is an idiom, not a count: it licenses no "1".
        ("Was one of the first engineers on the team.", "Was the #1 engineer on the team.", "1"),
        # Ordinary nouns ending in -ing are subjects, not outcome verbs.
        ("Grew funding by 20%.", "Boosted staffing by 20%.", "rebound:20 staffing"),
        ("Shortened training by 30%.", "Trimmed testing by 30%.", "rebound:30 testing"),
    ],
)
def test_real_alterations_still_fail(source, rewrite, expected):
    assert expected in _offenders(source, rewrite)


@pytest.mark.parametrize(
    ("source", "rewrite", "expected"),
    [
        # Versions, ranges, dates, fractions and ratios stay whole.
        ("Migrated prompts to GPT-4.1 for evaluation.", "Migrated prompts to GPT-5 for evaluation.",
         "GPT-5"),
        ("Shipped fixes in 2-3 weeks per release.", "Shipped fixes in 3 weeks per release.",
         "missing_number:2-3"),
        ("Provided 24/7 on-call support for the API.", "Provided 24 hour on-call support for the API.",
         "missing_number:24/7"),
        ("Closed the quarter on 10/15 with the audit.", "Closed the quarter in October with the audit.",
         "missing_number:10/15"),
        ("Reduced the error rate to 1/2 of baseline.", "Reduced the error rate to 1 of baseline.",
         "missing_number:1/2"),
    ],
)
def test_existing_rejections_survive(source, rewrite, expected):
    assert expected in _offenders(source, rewrite)


def test_number_words_license_only_their_own_digits():
    allowed = fabrication._vocabulary(Bullet(id="b", text="Led a team of three across two sites."))
    assert {"3", "2"} <= allowed
    assert "4" not in allowed and "30" not in allowed
