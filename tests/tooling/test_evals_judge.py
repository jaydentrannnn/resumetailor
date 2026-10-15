"""Eval harness judge (`scripts/evals/judge.py`): order-swapped verdicts and the batch.

The model is replaced by an `asker` function; nothing here reaches a network.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import judge, report  # noqa: E402

from resume_tailor import config  # noqa: E402


def _always(letter: str):
    return lambda _user, _stage: judge.Verdict(winner=letter, reason="r")


def _prefers(text: str):
    """A consistent judge: picks whichever side shows `text` in its <A> block."""
    def ask(user: str, _stage: str) -> judge.Verdict:
        a_block = user.split("<A>", 1)[1].split("</A>", 1)[0]
        return judge.Verdict(winner="A" if text in a_block else "B", reason="r")
    return ask


def _build(a: str, b: str) -> str:
    return f"<A>{a}</A><B>{b}</B>"


def test_a_win_counts_only_when_both_orders_agree():
    assert judge.both_orders(_build, "good", "bad", "rewrite", asker=_prefers("good"))["winner"] == "a"
    assert judge.both_orders(_build, "bad", "good", "rewrite", asker=_prefers("good"))["winner"] == "b"


def test_a_judge_that_always_picks_the_first_version_scores_a_tie():
    verdict = judge.both_orders(_build, "x", "y", "rewrite", asker=_always("A"))
    assert verdict["winner"] == "tie"
    assert verdict["consistent"] is False


def test_two_ties_are_a_consistent_tie():
    verdict = judge.both_orders(_build, "x", "y", "rewrite", asker=_always("tie"))
    assert (verdict["winner"], verdict["consistent"]) == ("tie", True)


def test_rewrite_prompt_shows_source_and_both_versions_per_bullet():
    build = judge.rewrite_prompt("Data Analyst", ["SQL"], {"b1": "Wrote queries."})
    text = build({"b1": "Wrote SQL queries."}, {})
    assert "Must-haves: SQL" in text
    assert "<source>Wrote queries.</source>" in text
    assert "<A>Wrote SQL queries.</A>" in text
    assert "<B>Wrote queries.</B>" in text  # a missing id falls back to the source


def test_extract_prompt_lists_keywords_with_importance():
    build = judge.extract_prompt("We need Excel.")
    text = build({"keywords": [{"phrase": "Excel", "importance": "must_have"}]},
                 {"keywords": []})
    assert "<posting>\nWe need Excel.\n</posting>" in text
    assert "- [must_have] Excel" in text


def test_judge_spec_is_a_custom_openai_compatible_backend():
    spec = judge.spec("https://res.openai.azure.com/openai/v1/", "gpt-judge")
    assert spec["origin"] == "custom" and spec["provider"] == "openai"
    assert spec["base_url"] == "https://res.openai.azure.com/openai/v1"
    assert spec["credential_ref"].startswith("CUSTOM_HEAVY_")


def test_batch_judges_under_the_judge_model_resumes_and_records_errors(tmp_path):
    spec = judge.spec("https://res.openai.azure.com/openai/v1", "gpt-judge")
    seen_models = []

    def ask(user: str, stage: str) -> judge.Verdict:
        seen_models.append(config.model_for("review"))
        if "boom" in user:
            raise RuntimeError("server error")
        return _prefers("good")(user, stage)

    jobs = [("c1", "medium#0", "low#0", _build, "good", "bad"),
            ("c2", "medium#0", "low#0", _build, "boom", "bad")]
    verdicts = judge.Verdicts(tmp_path / "judge.jsonl")

    first = judge.run(jobs, "rewrite", spec, verdicts, workers=2, asker=ask)

    assert set(seen_models) == {"gpt-judge"}
    by_case = {r["case"]: r for r in first}
    assert by_case["c1"]["winner"] == "a"
    assert "RuntimeError: server error" in by_case["c2"]["error"]
    assert report.judge_tally(verdicts.records(), "medium#0", "low#0") == {"a": 1, "b": 0, "tie": 0}

    second = judge.run(jobs, "rewrite", spec, verdicts, workers=1, asker=ask)
    assert [r["case"] for r in second] == ["c2"]  # finished pairs are not re-judged
