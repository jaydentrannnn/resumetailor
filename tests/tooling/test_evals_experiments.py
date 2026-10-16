"""Experiment plumbing for E1/E2 (`scripts/evals`): sequential decisions, case-level
bootstrap, eval-only variants, frozen-draft polish, and the end-to-end gates.

No model calls: polish and fit are fakes, and the worker launcher runs a trivial script.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import e2e, report_seq, sequential, stages, variants  # noqa: E402
from evals.sequential import Bound, Criterion  # noqa: E402

from resume_tailor.content.data import Bullet  # noqa: E402
from resume_tailor.pipeline import rewrite, rewrite_prompts  # noqa: E402
from resume_tailor.pipeline.jd import JobRequirements, Keyword  # noqa: E402

# --- bootstrap and decisions ----------------------------------------------------------


def test_bounds_bracket_the_mean_and_collapse_on_constant_data():
    b = sequential.bounds([1, 0, 0, -1, 1, 1, 0, 1] * 5)
    assert b.lower <= b.estimate <= b.upper and b.n == 40
    flat = sequential.bounds([0.5] * 10)
    assert flat.lower == flat.estimate == flat.upper == 0.5


def test_one_sided_bound_is_tighter_than_a_two_sided_95_interval():
    values = [1, -1, 0, 0, 1, 0, -1, 1, 0, 1] * 4
    one = sequential.bounds(values)
    wide = sequential.bounds(values, alpha=0.025)
    assert wide.lower <= one.lower and one.upper <= wide.upper


def test_ratio_bounds_measure_relative_cost():
    pairs = [(1.0, 1.1), (2.0, 2.2), (4.0, 4.4)]
    assert sequential.ratio_bounds(pairs).estimate == pytest.approx(0.10)
    assert sequential.ratio_bounds([(1.0, None), (1.0, 1.0)]).n == 1


def _crit(lower, upper, bar, higher=True, strict=False):
    return Criterion("c", Bound((lower + upper) / 2, lower, upper, 40), bar, higher, strict)


@pytest.mark.parametrize(("lower", "upper", "look", "expected"), [
    (-0.05, 0.20, 1, "PASS"),       # lower bound clears -10 points
    (-0.40, -0.15, 1, "FUTILE"),    # even the upper bound misses it
    (-0.30, 0.10, 1, "CONTINUE"),
    (-0.30, 0.10, 2, "FAIL"),       # anything but PASS at the last look
    (-0.05, 0.20, 2, "PASS"),
])
def test_non_inferiority_decisions(lower, upper, look, expected):
    assert _crit(lower, upper, -0.10).decision(look) == expected


def test_lower_is_better_and_strict_bars():
    assert _crit(-0.1, 0.05, 0.10, higher=False).decision(1) == "PASS"
    assert _crit(0.15, 0.40, 0.10, higher=False).decision(1) == "FUTILE"
    assert _crit(0.0, 0.3, 0.0, strict=True).decision(1) == "CONTINUE"
    assert _crit(0.0, 0.3, 0.0).decision(1) == "PASS"


def test_too_few_cases_never_pass():
    nan = float("nan")
    c = Criterion("c", Bound(nan, nan, nan, 1), 0.0, True)
    assert c.decision(1) == "CONTINUE" and c.decision(2) == "FAIL"
    smoke = Criterion("c", Bound(0.5, 0.4, 0.6, 5), 0.0, True)
    assert smoke.decision(1) == "CONTINUE"


def test_decide_needs_every_criterion_and_stops_on_futility():
    good, futile, open_ = _crit(0, 1, -0.1), _crit(-1, -0.5, -0.1), _crit(-0.5, 0.5, -0.1)
    assert sequential.decide([good, good], 1) == "PASS"
    assert sequential.decide([good, futile, open_], 1) == "FUTILE"
    assert sequential.decide([good, open_], 1) == "CONTINUE"
    assert sequential.decide([good, open_], 2) == "FAIL"


def test_case_scores_one_observation_per_case():
    verdicts = [
        {"case": "1", "a": "x", "b": "y", "winner": "a"},
        {"case": "1", "a": "x", "b": "y", "winner": "b"},  # a rerun: the last one wins
        {"case": "2", "a": "x", "b": "y", "winner": "tie"},
        {"case": "3", "a": "x", "b": "y", "error": "boom"},
        {"case": "4", "a": "x", "b": "z", "winner": "b"},
        {"case": "5", "a": "x", "b": "y", "winner": "a", "reasons": ["45% -> 96.3%", ""]},
    ]
    assert sequential.case_scores(verdicts, "x", "y") == {"1": 1, "2": 0, "5": -1}
    assert sequential.case_scores(verdicts, "x", "y", cases=["2"]) == {"2": 0}
    cited = sequential.case_scores(verdicts, "x", "y",
                                   exclude=lambda v: sequential.cites(v, r"96\.3"))
    assert cited == {"1": 1, "2": 0}


# --- E1 / E2 reporting --------------------------------------------------------------------


def test_e1_fixed_sequence():
    assert report_seq.e1_choice("PASS", "FAIL", 1) == "ship polish none"
    assert report_seq.e1_choice("CONTINUE", "PASS", 1).startswith("extend")
    assert report_seq.e1_choice("FUTILE", "PASS", 1) == "ship polish low"
    assert report_seq.e1_choice("FUTILE", "CONTINUE", 1).startswith("extend")
    assert report_seq.e1_choice("FAIL", "FAIL", 2) == "keep medium polish"


def _rec(shown, backed, usage=None, **metrics):
    return {"result": {"must": {"shown": shown, "backed": backed}, "metrics": metrics},
            "usage": usage or {}}


def test_supported_losses_count_only_backed_keywords():
    base = _rec(["SQL", "Python", "Kafka"], ["SQL", "Python"])
    cand = _rec(["Kafka", "Go"], ["SQL", "Python", "Go"])
    assert report_seq.supported_losses(base, cand) == (2, 0)


def test_e2_cost_compares_whole_rewrites():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    grouped = {"draft#0": {"c": _rec([], [], usage)}, report_seq.BASE: {"c": _rec([], [], usage)},
               "clause#0": {"c": _rec([], [], usage)}}
    (base, cand), = report_seq.e2_cost_pairs(grouped, ["c"], "gemini-3.8-flash")
    assert base == pytest.approx(2 * cand)


# --- variants -----------------------------------------------------------------------------


@pytest.fixture
def fresh_variants(monkeypatch):
    """Install the variant wrappers over test-owned seams, restored afterwards."""
    calls = []

    def fake_polish(out, *args, **kwargs):
        calls.append(kwargs.get("effort"))
        return {k: v + "!" for k, v in out.items()}, 0, 1, {}

    monkeypatch.setattr(rewrite_prompts, "_system", lambda: "Rules\n" + "Return one entry "
                        "per input item, keyed by the exact id you were given.\n")
    monkeypatch.setattr(rewrite, "cosmetic_polish", fake_polish)
    monkeypatch.setattr(variants, "_installed", False)
    monkeypatch.delenv(variants.CLAUSE_ENV, raising=False)
    monkeypatch.delenv(variants.POLISH_ENV, raising=False)
    variants.install()
    return calls


def test_clause_goes_just_above_the_return_shape():
    text = variants.with_clause(rewrite_prompts._SYSTEM)
    assert text.index(variants.CLAUSE) < text.index("Return one entry per input item")
    assert text.count("Return one entry") == 1
    # Every original rule survives, in order, with the clause as the last one.
    assert text.replace(variants.CLAUSE, "").replace("\n\n\n", "\n\n") \
        == rewrite_prompts._SYSTEM


def test_clause_only_when_switched_on(fresh_variants, monkeypatch):
    assert variants.CLAUSE not in rewrite_prompts._system()
    with variants.clause():
        assert variants.CLAUSE in rewrite_prompts._system()
    assert variants.CLAUSE not in rewrite_prompts._system()
    monkeypatch.setenv(variants.CLAUSE_ENV, "1")  # an end-to-end worker process
    assert variants.CLAUSE in rewrite_prompts._system()


def test_polish_effort_variants(fresh_variants, monkeypatch):
    out = {"a": "x"}
    assert rewrite.cosmetic_polish(out)[0] == {"a": "x!"}
    with variants.polish_effort("none"):
        assert rewrite.cosmetic_polish(out) == ({"a": "x"}, 0, 0, {})
    with variants.polish_effort("low"):
        rewrite.cosmetic_polish(out)
    monkeypatch.setenv(variants.POLISH_ENV, "none")
    assert rewrite.cosmetic_polish(out)[0] == {"a": "x"}
    assert fresh_variants == [None, "low"]  # "none" never reached the model


# --- frozen-draft polish stage ------------------------------------------------------------


def _replay():
    replay = object.__new__(stages.Replay)
    sources = [Bullet(id="a", text="Built a service in Python for billing.", tags=["python"]),
               Bullet(id="b", text="Wrote reports.", tags=[])]
    requirements = JobRequirements(title="Engineer", seniority="entry", keywords=[
        Keyword(phrase="Python", canonical="python", importance="must_have")])
    replay.sources = lambda case: sources
    replay._requirements = lambda case: requirements
    replay.budget = 200
    return replay


def test_polish_none_keeps_the_frozen_drafts(monkeypatch):
    monkeypatch.setattr(rewrite, "cosmetic_polish", lambda *a, **k: pytest.fail("called"))
    draft = {"texts": {"a": "Built a Python billing service.", "b": "Wrote reports."},
             "fabrications_rejected": {}}
    out = _replay().polish(None, draft, "none")
    assert out["texts"] == draft["texts"] and out["verbs_diversified"] == 0
    assert out["must"] == {"shown": ["Python"], "backed": ["Python"]}
    assert "guard_offenders" in out["metrics"]


def test_polish_passes_its_effort_to_the_polish_call(monkeypatch):
    seen = {}

    def fake(texts, by_id, requirements, *, repair_verbs, effort):
        seen.update(effort=effort, ids=sorted(by_id), repair_verbs=repair_verbs)
        return dict(texts), 0, 2, {}

    monkeypatch.setattr(rewrite, "cosmetic_polish", fake)
    draft = {"texts": {"a": "Built a Python billing service."}, "fabrications_rejected": {}}
    out = _replay().polish(None, draft, "low")
    assert seen == {"effort": "low", "ids": ["a", "b"], "repair_verbs": True}
    assert out["verbs_diversified"] == 2


# --- end to end -----------------------------------------------------------------------------


def _fit(pages=1, estimated=False, fill=0.95, widows=0, dropped=(), bullets=None):
    return SimpleNamespace(pages=pages, pages_are_estimated=estimated, fill_ratio=fill,
                           widows_remaining=widows, dropped=list(dropped), iterations=3,
                           bullets=bullets or {"a": "x"})


def _e2e(case, result, *, code=0, tokens=1000):
    usage = {"input_tokens": tokens, "output_tokens": tokens}
    return e2e.record(case, "arm", code=code, result=result, usage=usage, wall_s=10.0,
                      error=None, target_pages=1)


def test_estimated_or_unfitted_runs_count_as_failures():
    assert not e2e.failed(_e2e("1", _fit()))
    assert e2e.failed(_e2e("1", _fit(estimated=True)))
    assert e2e.failed(_e2e("1", None, code=-1))
    assert _e2e("1", _fit(pages=2))["over_target"]


CASES = [str(i) for i in range(4)]


def test_gates_pass_an_equivalent_arm_and_block_a_worse_one():
    base = {k: _e2e(k, _fit()) for k in CASES}
    same = {k: _e2e(k, _fit(), tokens=1050) for k in CASES}
    rows = e2e.gates(CASES, base, same, dict.fromkeys(CASES, 0), model="gemini-3.8-flash",
                     cost_limit=0.10)
    assert all(ok for *_, ok in rows)
    worse = {k: _e2e(k, _fit(fill=0.80, widows=2, estimated=k == "0"), tokens=1500)
             for k in CASES}
    failed = {g for g, _d, ok in e2e.gates(CASES, base, worse, dict.fromkeys(CASES, -1),
                                            model="gemini-3.8-flash", cost_limit=0.10)
              if not ok}
    assert {"failed or estimated runs", "mean fill change >= -2 points",
            "mean widows-remaining change <= +0.5", "judge net preference >= -10 points",
            "total cost <= +10%"} <= failed


def test_gates_never_pass_on_whatever_happened_to_finish():
    """20 baseline cases, one candidate case, a verdict for an unrelated case, and a
    candidate that took 100 fit rounds: every gap blocks."""
    cases = [str(i) for i in range(20)]
    base = {k: _e2e(k, _fit()) for k in cases}
    slow = _fit()
    slow.iterations = 100
    cand = {"0": _e2e("0", slow)}
    failed = {g for g, _d, ok in e2e.gates(cases, base, cand, {"unrelated": 1},
                                            model="gemini-3.8-flash", cost_limit=0.10)
              if not ok}
    assert {"every case ran in both arms", "judge net preference >= -10 points",
            "mean fit-round change <= +0.5"} <= failed


def test_a_sequential_decision_needs_every_declared_case():
    cases = [str(i) for i in range(40)]
    rec = _rec(["Python"], ["Python"], {"input_tokens": 1, "output_tokens": 1},
               guard_offenders=0, over_length=0)
    grouped = {report_seq.BASE: dict.fromkeys(cases, rec),
               "polish-none#0": dict.fromkeys(cases[:20], rec)}
    verdicts = [{"case": c, "a": report_seq.BASE, "b": "polish-none#0", "winner": "b"}
                for c in cases[:20]]
    crit = report_seq.e1_criteria(grouped, verdicts, "none", cases)
    assert sequential.decide(crit, 1) == "PASS"  # what the finished half alone would say
    gap = report_seq.e1_missing(grouped, verdicts, "none", cases)
    assert gap == cases[20:]
    assert sequential.decide(crit, 1, missing=gap) == "INCOMPLETE"
    assert report_seq.e1_choice("INCOMPLETE", "PASS", 1).startswith("incomplete")


def test_the_guard_metric_counts_dropped_numbers_like_production():
    from evals import metrics

    source = Bullet(id="a", text="Built an API handling 42 requests per second.", tags=[])
    reqs = JobRequirements(title="Engineer", seniority="entry", keywords=[])
    out = metrics.rewrite_metrics([source], {"a": "Built an API."}, {}, reqs, 200)
    assert out["guard_offenders"] >= 1


def test_workers_are_separate_processes_with_the_arm_environment(tmp_path):
    out = tmp_path / "workers"
    out.mkdir()
    script = ("import os, pathlib; pathlib.Path(os.environ['OUT'], str(os.getpid()))"
              ".write_text(os.environ['RT_EVAL_CLAUSE'])")
    bad = e2e.launch([sys.executable, "-c", script],
                     {"OUT": str(out), "RT_EVAL_CLAUSE": "1"}, workers=3)
    files = list(out.iterdir())
    assert bad == 0 and len(files) == 3 and str(os.getpid()) not in {f.name for f in files}
    assert {f.read_text() for f in files} == {"1"}
