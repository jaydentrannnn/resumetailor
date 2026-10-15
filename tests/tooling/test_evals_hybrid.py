"""Experiment E pieces (`scripts/evals`): the dictionary scan, the labelling call, the
non-tech fetcher, and E's report rules. No network: boards and the model are fakes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import fetch, hybrid_extract, report_extract  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.pipeline.jd import JobRequirements, Keyword  # noqa: E402


def _reqs(*phrases: str) -> JobRequirements:
    return JobRequirements(title="t", seniority="entry", keywords=[
        Keyword(phrase=p, canonical=p.lower(), importance="must_have") for p in phrases])


# --- dictionary and scan ----------------------------------------------------------------


def test_leave_one_out_drops_phrases_only_the_posting_itself_contributed():
    d = hybrid_extract.Dictionary(base_terms=["python"])
    d.add_extraction("p1", _reqs("Kafka", "SQL"))
    d.add_extraction("p2", _reqs("SQL"))

    assert set(d.phrases(excluding="p1")) == {"python", "sql"}
    assert set(d.phrases(excluding="p2")) == {"python", "sql", "kafka"}
    assert set(d.phrases()) == {"python", "sql", "kafka"}


def test_base_terms_and_aliases_are_never_left_out():
    d = hybrid_extract.Dictionary(base_terms=["excel"], aliases={"k8s": "kubernetes"})
    d.add_extraction("p1", _reqs("Excel"))
    assert {"excel", "k8s", "kubernetes"} <= set(d.phrases(excluding="p1"))
    assert d.canonical["k8s"] == "kubernetes"


def test_short_language_names_need_the_postings_capitals():
    text = "We go fast. Experience with Go and R, plus C# and C++. Know ML. Grade c."
    found = {surface for surface, _ in hybrid_extract.candidates(
        text, ["go", "r", "c#", "c++", "ml", "c"])}
    assert found == {"Go", "R", "C#", "C++", "ML"}


def test_scan_keeps_the_postings_spelling_and_order_and_prefers_longer_phrases():
    text = "Strong Machine   Learning skills; SQL a plus; learning culture."
    found = hybrid_extract.candidates(text, ["machine learning", "learning", "sql"])
    assert [s for s, _ in found] == ["Machine   Learning", "SQL", "learning"]


def test_a_phrase_inside_a_longer_match_is_not_listed_twice():
    found = hybrid_extract.candidates("Machine learning only.", ["machine learning", "learning"])
    assert [p for _, p in found] == ["machine learning"]


def test_letters_inside_words_never_match():
    assert hybrid_extract.candidates("Rust and Erlang", ["r", "go"]) == []


# --- labelling call ---------------------------------------------------------------------


class _Messages:
    def __init__(self, calls, reply):
        self.calls, self.reply = calls, reply

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.reply, stop_reason="end_turn")


def test_the_labelling_call_is_the_current_prompt_plus_candidates(monkeypatch):
    calls: list[dict] = []
    reply = _reqs("Excel", "Kubernetes")
    reply.keywords[1].canonical = "k8s"
    reply.keywords[0].evidence, reply.keywords[0].band = "inferred", "critical"
    monkeypatch.setattr(hybrid_extract.llm, "client_for",
                        lambda purpose: SimpleNamespace(messages=_Messages(calls, reply)))
    monkeypatch.setattr(config, "canonical_tag", lambda t: "kubernetes" if t == "k8s" else t)
    d = hybrid_extract.Dictionary(base_terms=["excel"])

    requirements, found = hybrid_extract.extract(
        "Advanced Excel required.", d, known_tags=["excel"])

    assert found == 1
    user = calls[0]["messages"][0]["content"]
    assert "<job_description>\nAdvanced Excel required.\n</job_description>" in user
    assert "<known_tags>\nexcel\n</known_tags>" in user
    assert "<dictionary_candidates>\n- Excel (excel)\n</dictionary_candidates>" in user
    assert calls[0]["output_format"] is JobRequirements
    assert requirements.keywords[1].canonical == "kubernetes"  # canonicalised like jd.extract
    assert requirements.keywords[0].band == "meaningful"  # evidence cap applied


# --- fetcher ----------------------------------------------------------------------------


def _job(job_id: str, title: str):
    return SimpleNamespace(id=job_id, title=title, url=f"https://x/{job_id}")


def test_title_filter_keeps_non_tech_roles_of_the_group():
    assert fetch.wanted("Investment Banking Analyst", "finance")
    assert not fetch.wanted("Software Engineer, Payments", "finance")
    assert not fetch.wanted("Technology Risk Analyst", "finance")
    assert fetch.wanted("Registered Nurse, Care Team", "nontech")
    assert not fetch.wanted("Senior Data Scientist", "nontech")
    assert not fetch.wanted("Career Fair Volunteer", "nontech")


def test_fetch_saves_text_and_sidecar_caps_per_board_and_skips_dead_boards(tmp_path):
    jobs = {"bank": [_job("1", "Credit Analyst"), _job("2", "Audit Associate"),
                     _job("3", "Treasury Analyst"), _job("4", "Software Engineer")]}

    def lister(ats, slug):
        if slug not in jobs:
            raise RuntimeError("404")
        return jobs[slug]

    logs: list[str] = []
    have = fetch.fetch(
        tmp_path, [{"ats": "greenhouse", "slug": "gone"},
                   {"ats": "greenhouse", "slug": "bank", "company": "Big Bank"}],
        group="finance", workspace="nina", per_board=2, total=10, lister=lister,
        fetcher=lambda ats, slug, job: f"Posting {job.id}", log=logs.append)

    assert have == 2
    assert any("skip greenhouse:gone" in line for line in logs)
    sidecars = sorted(tmp_path.glob("*.json"))
    meta = json.loads(sidecars[0].read_text("utf-8"))
    assert (meta["group"], meta["workspace"], meta["company"]) == ("finance", "nina", "Big Bank")
    assert sidecars[0].with_suffix(".txt").read_text("utf-8").startswith("Posting ")

    again = fetch.fetch(tmp_path, [{"ats": "greenhouse", "slug": "bank"}], group="finance",
                        workspace="nina", per_board=2, total=2, lister=lister,
                        fetcher=lambda *a: "x", log=logs.append)
    assert again == 2  # already at the total: nothing new fetched
    assert len(list(tmp_path.glob("*.txt"))) == 2


# --- E's report -------------------------------------------------------------------------


def _record(case, arm, group, shown, total, phrases, repeat=0, wall=1000, out=100):
    return {
        "status": "ok", "case": case, "arm": arm, "repeat": repeat, "group": group,
        "tags": [],
        "result": {
            "metrics": {"must_shown": shown, "must_total": total, "keywords": len(phrases),
                        "must_haves": len(phrases), "verbatim_violations": 0,
                        "keywords_shown": shown},
            "requirements": {"keywords": [
                {"canonical": p, "phrase": p, "importance": "must_have"} for p in phrases]},
        },
        "usage": {"calls": 1, "input_tokens": 10, "output_tokens": out,
                  "reasoning_tokens": 0, "request_ms": 1, "wall_ms": wall},
    }


def test_e_fails_when_non_tech_coverage_does_not_improve():
    records = [
        _record("t1", "current", "tech", 3, 4, ["a", "b"]),
        _record("t1", "hybrid", "tech", 3, 4, ["a", "b"]),
        _record("f1", "current", "finance", 1, 4, ["x"]),
        _record("f1", "hybrid", "finance", 1, 4, ["x"]),
    ]
    rules = report_extract.rules(records, [], None)
    assert rules[0].passed is True  # tech not worse
    assert rules[1].passed is False  # non-tech not better
    assert "FAIL" in report_extract.markdown(records, [], None)


def test_cases_where_the_resume_shows_nothing_are_left_out_of_coverage():
    def rec(case, arm, group, kw_shown, shown=0):
        r = _record(case, arm, group, shown, 4, ["x"])
        r["result"]["metrics"]["keywords_shown"] = kw_shown
        return r

    records = [rec("f1", "current", "finance", 0), rec("f1", "hybrid", "finance", 0),
               rec("n1", "current", "nontech", 2, 1), rec("n1", "hybrid", "nontech", 3, 2)]
    rule = report_extract.rules(records, [], None)[1]
    assert rule.passed is True
    assert "n=1" in rule.detail


def test_cross_model_agreement_compares_each_method_across_models():
    records = [
        _record("t1", "current", "tech", 1, 1, ["a", "b"]),
        _record("t1", "current@azure", "tech", 1, 1, ["c", "d"]),
        _record("t1", "hybrid", "tech", 1, 1, ["a", "b"]),
        _record("t1", "hybrid@azure", "tech", 1, 1, ["a", "b"]),
    ]
    rule = next(r for r in report_extract.rules(records, [], "azure") if "cross-model" in r.text)
    assert rule.passed is True
    assert "current 0.000" in rule.detail and "hybrid 1.000" in rule.detail
