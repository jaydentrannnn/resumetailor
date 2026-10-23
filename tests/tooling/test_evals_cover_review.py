"""Experiments 4d/4e plumbing (`scripts/evals`): the cover-letter gap-bridge variant, the
broader review, their metrics and judge prompts. No model calls: the review client is a
hand-written fake."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import judge, metrics, review_scope, stages, variants  # noqa: E402

from resume_tailor.content.data import Bullet  # noqa: E402
from resume_tailor.pipeline import coverletter  # noqa: E402
from resume_tailor.pipeline.jd import JobRequirements, Keyword  # noqa: E402
from tests.fixtures import synthetic_resume  # noqa: E402


@pytest.fixture
def fresh_gaps(monkeypatch):
    """Install the gap wrappers for this test only; teardown restores the originals."""
    monkeypatch.setattr(variants, "_gaps_installed", False)
    for name in ("_system", "_user_message", "_check_fabrication"):
        monkeypatch.setattr(coverletter, name, getattr(coverletter, name))


def _requirements(*must: str) -> JobRequirements:
    return JobRequirements(
        title="Data Analyst", seniority="intern",
        keywords=[Keyword(phrase=m, canonical=m.lower(), importance="must_have") for m in must],
    )


def test_gap_variant_is_a_no_op_until_a_task_sets_gaps(fresh_gaps):
    variants.install_gaps()
    resume = synthetic_resume()
    kwargs = dict(resume=resume, requirements=_requirements("SQL"), bullets={},
                  jd_text="We need SQL.", word_band=(200, 300))
    plain_user, plain_system = coverletter._user_message(**kwargs), coverletter._system()
    assert "<unmet_requirements>" not in plain_user and variants.GAP_RULE not in plain_system
    with variants.gaps(["Kubernetes", "Go"]):
        user, system = coverletter._user_message(**kwargs), coverletter._system()
    assert user.index("<unmet_requirements>\n- Kubernetes\n- Go\n") < user.index(
        coverletter._POSTING_FRAME)
    assert system.index(variants.GAP_RULE) < system.index("Return a JSON object")
    assert coverletter._user_message(**kwargs) == plain_user


def test_the_guard_lets_a_gap_through_only_when_the_sentence_says_it_is_not_held(fresh_gaps):
    variants.install_gaps()
    sources = [Bullet(id="b1", text="Built SQL dashboards for the finance team", tags=["SQL"])]
    honest = "While I have not used Kubernetes yet, I built SQL dashboards."
    claim = "I deployed Kubernetes clusters and built SQL dashboards."
    assert "kubernetes" in [o.lower() for o in coverletter._check_fabrication(sources, honest)]
    with variants.gaps(["Kubernetes"]):
        assert coverletter._check_fabrication(sources, honest) == []
        assert coverletter._check_fabrication(sources, claim)


def test_cover_metrics_count_named_and_claimed_gaps():
    paragraphs = ["I built Kubernetes clusters on every project. I have not used Go yet, but I "
                  "learn fast. Your team's Rust services interest me."]
    warnings = ["AI tell: passionate", "Unsupported claims remain after retry: kubernetes"]
    m = metrics.cover_metrics(paragraphs, warnings, 24, ["Kubernetes", "Go", "Rust"])
    assert (m["gap_mentioned"], m["gap_claimed"], m["factual_left"], m["ai_tells"]) == (3, 1, 1, 1)


def test_review_metrics_share_dropped_suggestions_and_count_findings():
    record = {"bullets": [
        {"verdict": "rewrite", "offered": True, "dropped_note": "rewrite dropped (x)"},
        {"verdict": "keep", "offered": False, "dropped_note": "", "scope_risk": "stretch",
         "softer_offered": True, "softer_dropped": ""},
        {"verdict": "cut", "offered": False, "dropped_note": ""},
    ], "consistency": ["Dates disagree"]}
    m = metrics.review_metrics(record)
    assert m["guard_dropped_rate"] == 0.5
    assert (m["cuts"], m["rewrites"], m["stretch"], m["findings"]) == (1, 1, 1, 4)


def test_unmet_lists_missing_must_haves_in_posting_order_capped():
    replay = stages.Replay.__new__(stages.Replay)
    replay.known_tags = ["sql"]
    # Named in the resume's text but not a known skill: not a gap to disclaim.
    replay._resume_text = "Mentored students in object-oriented programming"
    requirements = _requirements("SQL", "Object-oriented programming", "Kubernetes", "Go", "Rust")
    case = SimpleNamespace(requirements_json=requirements.model_dump_json)
    assert replay.unmet(case) == ["Kubernetes", "Go"]


def test_scoped_review_guards_both_suggestions(monkeypatch):
    resume = synthetic_resume()
    bullet = resume.all_bullets()[0]
    reply = review_scope.ScopedReviewLLM(scope_read="Analyst role", consistency=["None"], bullets=[
        review_scope.ScopedVerdict(
            id=bullet.id, verdict="rewrite", reason="close", replacement=bullet.text,
            scope_risk="stretch", scope_note="Sounds like sole ownership",
            softer_replacement=bullet.text + " using Kubernetes"),
        review_scope.ScopedVerdict(id="not-on-page", verdict="cut", reason="off topic"),
    ])
    calls = []

    class _Messages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(parsed_output=reply, stop_reason="end_turn")

    monkeypatch.setattr(review_scope.llm, "client_for",
                        lambda purpose: SimpleNamespace(messages=_Messages()))
    record = review_scope.review_scoped(resume, _requirements("SQL"), {bullet.id: bullet.text},
                                        ["My cover letter."])
    [row] = record["bullets"]
    assert row["replacement"] == bullet.text and row["softer"] == ""
    assert row["softer_dropped"].startswith("dropped (fabricated")
    assert "<cover_letter>\nMy cover letter.\n</cover_letter>" in calls[0]["messages"][0]["content"]
    assert calls[0]["system"].startswith(review_scope.review._BASE_SYSTEM)


def test_note_variant_is_the_frozen_baseline_plus_the_flag(monkeypatch):
    resume = synthetic_resume()
    bullet = resume.all_bullets()[0]
    calls = []

    class _Messages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            shape = kwargs["output_format"]
            reply = shape(bullets=[{
                "id": bullet.id, "verdict": "keep", "reason": "fits",
                "scope_risk": "stretch", "scope_note": "Team size unclear",
            }]) if shape is review_scope.NotedReviewLLM else shape()
            return SimpleNamespace(parsed_output=reply, stop_reason="end_turn")

    monkeypatch.setattr(review_scope.llm, "client_for",
                        lambda purpose: SimpleNamespace(messages=_Messages()))
    bullets = {bullet.id: bullet.text}
    record = review_scope.review_scoped(resume, _requirements("SQL"), bullets,
                                        ["My cover letter."], variant="note")
    review_scope.review_scoped(resume, _requirements("SQL"), bullets, variant="baseline")
    noted, baseline = calls
    assert noted["messages"] == baseline["messages"]
    assert noted["system"].startswith(baseline["system"])
    assert "scope_risk" in noted["system"] and "scope_risk" not in baseline["system"]
    assert "softer" not in noted["system"] and "consistency" not in noted["system"]
    [row] = record["bullets"]
    assert (row["scope_risk"], row["scope_note"], row["softer_offered"]) == (
        "stretch", "Team size unclear", False)
    assert record["consistency"] == []
    assert metrics.review_metrics(record)["stretch"] == 1
    monkeypatch.setattr(review_scope.review, "_SYSTEM", "A future production review")
    monkeypatch.setattr(review_scope.review, "_BASE_SYSTEM", "A future production baseline")
    review_scope.review_scoped(resume, _requirements("SQL"), bullets, variant="note")
    assert calls[-1]["system"] == noted["system"]
    assert calls[-1]["output_format"] is noted["output_format"]


def test_review_experiments_keep_the_pre_note_baseline_after_production_changes(monkeypatch):
    import eval_models

    resume = synthetic_resume()
    bullet = resume.all_bullets()[0]
    calls = []

    class _Messages:
        def parse(self, **kwargs):
            calls.append(kwargs)
            shape = kwargs["output_format"]
            return SimpleNamespace(parsed_output=shape(), stop_reason="end_turn")

    monkeypatch.setattr(review_scope.llm, "client_for",
                        lambda purpose: SimpleNamespace(messages=_Messages()))
    monkeypatch.setattr(review_scope.review, "_SYSTEM", "A future production review")
    replay = stages.Replay.__new__(stages.Replay)
    replay.resume = resume
    requirements = _requirements("SQL")
    monkeypatch.setattr(replay, "_requirements", lambda case: requirements)
    monkeypatch.setattr(replay, "tailored", lambda case: {bullet.id: bullet.text})
    for stage in ("review", "review-note"):
        base, _candidate, methods = eval_models._VARIANTS[stage]
        record = getattr(replay, methods[base])(None)
        assert record["metrics"]["stretch"] == 0
    for call in calls:
        assert call["system"].startswith("You are a hiring manager")
        assert "scope_risk" not in call["system"]
        schema = call["output_format"].model_json_schema()
        verdict = schema["$defs"]["BulletVerdict"]["properties"]
        assert set(verdict) == {"id", "verdict", "reason", "replacement"}
        assert "tailored_bullets" in call["messages"][0]["content"]


def test_frozen_review_baseline_still_drops_fabricated_rewrites(monkeypatch):
    resume = synthetic_resume()
    bullet = resume.all_bullets()[0]

    class _Messages:
        def parse(self, **kwargs):
            shape = kwargs["output_format"]
            reply = shape(bullets=[
                {"id": bullet.id, "verdict": "rewrite", "reason": "clearer",
                 "replacement": bullet.text + " using Kubernetes"},
                {"id": "not-on-page", "verdict": "cut"},
            ])
            return SimpleNamespace(parsed_output=reply, stop_reason="end_turn")

    monkeypatch.setattr(review_scope.llm, "client_for",
                        lambda purpose: SimpleNamespace(messages=_Messages()))
    replay = stages.Replay.__new__(stages.Replay)
    replay.resume = resume
    monkeypatch.setattr(replay, "_requirements", lambda case: _requirements("SQL"))
    monkeypatch.setattr(replay, "tailored", lambda case: {bullet.id: bullet.text})
    record = replay.review(None)
    [row] = record["bullets"]
    assert row["replacement"] == "" and row["offered"] is True
    assert row["dropped_note"].startswith("rewrite dropped (fabricated:")
    assert record["metrics"]["guard_dropped_rate"] == 1


def test_judge_prompts_show_both_sides():
    cover = judge.cover_prompt("Analyst", ["SQL"], "Acme\n- Built SQL")(["Para A"], ["Para B"])
    assert "<A>\nPara A\n</A>" in cover and "<resume>" in cover and "Must-haves: SQL" in cover
    row = {"id": "b1", "verdict": "keep", "reason": "fits", "scope_risk": "stretch",
           "scope_note": "scale", "softer": "Helped build"}
    review = judge.review_prompt("Analyst", [], {"b1": "Built it"})(
        {"bullets": [row], "consistency": ["Dates"]}, {"bullets": [], "consistency": []})
    assert "Possible stretch: scale Softer: Helped build" in review
    assert "- Consistency: Dates" in review and "<B>\n(no findings)\n</B>" in review
    assert "cover" in judge._RUBRIC and "review" in judge._RUBRIC


@pytest.fixture
def fresh_company(monkeypatch):
    """Install the company-facts wrappers for this test only."""
    from resume_tailor.pipeline import coverletter_style

    monkeypatch.setattr(variants, "_company_installed", False)
    for name in ("_system", "_user_message"):
        monkeypatch.setattr(coverletter, name, getattr(coverletter, name))
    monkeypatch.setattr(coverletter_style, "_numbers_not_in_source",
                        coverletter_style._numbers_not_in_source)


def test_company_variant_frames_the_facts_before_the_posting(fresh_company):
    variants.install_company()
    kwargs = dict(resume=synthetic_resume(), requirements=_requirements("SQL"), bullets={},
                  jd_text="We need SQL.", word_band=(200, 300))
    plain = coverletter._user_message(**kwargs)
    with variants.company(["Acme serves 5 million businesses."]):
        user, system = coverletter._user_message(**kwargs), coverletter._system()
    assert "<company_facts>" not in plain and variants.COMPANY_RULE not in coverletter._system()
    assert user.index(variants.COMPANY_FRAME) < user.index("<company_facts>\n- Acme serves")
    assert user.index("</company_facts>") < user.index(coverletter._POSTING_FRAME)
    assert system.index(variants.COMPANY_RULE) < system.index("Return a JSON object")


def test_a_fact_number_passes_only_outside_first_person_claims(fresh_company):
    from resume_tailor.pipeline import coverletter_style

    variants.install_company()
    about = "Acme serves 5 million businesses, and I want to help."
    claim = "I built tools for 5 million users."
    assert coverletter_style._numbers_not_in_source(about, [], "") == ["5"]
    with variants.company(["Acme serves 5 million businesses."]):
        assert coverletter_style._numbers_not_in_source(about, [], "") == []
        assert coverletter_style._numbers_not_in_source(f"{about} {claim}", [], "") == ["5"]
        assert coverletter_style._numbers_not_in_source("Acme has 900 staff.", [], "") == ["900"]


def test_the_company_judge_sees_the_facts_and_its_own_rubric():
    build = judge.cover_prompt("Analyst", ["SQL"], "Acme\n- Built SQL", ["Acme makes maps."])
    text = build(["A"], ["B"])
    assert text.index("<company_facts>\n- Acme makes maps.\n") < text.index("<A>")
    assert "<company_facts>" not in judge.cover_prompt("Analyst", [], "R")(["A"], ["B"])
    assert "copied wrong" in judge.system("cover-company")


def test_the_site_guess_needs_the_page_to_name_the_company(monkeypatch):
    from resume_tailor.infra.polite_fetch import Fetched, FetchError

    class _Fetcher:
        def __init__(self, page):
            self.page, self.asked = page, []

        def get(self, url):
            self.asked.append(url)
            if self.page is None:
                raise FetchError("down")
            return Fetched(url, "text/html", self.page)

    named = _Fetcher("<title>Acme Analytics</title><p>Dashboards.</p>")
    assert stages._guess_site("Acme Analytics, Inc.", named) == "https://www.acmeanalytics.com/"
    assert stages._guess_site("Acme Analytics", _Fetcher("<p>Domain for sale</p>")) == ""
    assert stages._guess_site("Acme Analytics", _Fetcher(None)) == ""


def test_every_variant_stage_has_a_judge_rubric():
    import eval_models

    assert set(eval_models._VARIANTS) <= set(judge._RUBRIC)
