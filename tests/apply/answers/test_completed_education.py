"""Completed qualifications stay separate from the degree on a student's resume."""

from types import SimpleNamespace

import pytest

from resume_tailor.apply.answers import (
    answer,
    answer_facts,
    answer_memory,
    custom_answers,
    education,
    hybrid_resolver,
    questions,
)
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.forms import field_catalog, field_matcher, fill_state
from resume_tailor.apply.forms.field_types import FieldObservation, ObservedOption
from resume_tailor.apply.funnel import packet_fields, packet_models, packet_profile_fields
from tests.fixtures import synthetic_resume


@pytest.mark.parametrize(
    "label,key",
    [
        ("Highest education completed", education.KEY),
        ("What is the highest level of education you have obtained?", education.KEY),
        ("Highest degree", education.KEY),
        ("Educational attainment", education.KEY),
        ("What degree are you currently pursuing?", "degree_level"),
        (
            "Please select your highest level of education obtained or, if a current student, "
            "select the degree you are pursuing",
            education.MIXED_KEY,
        ),
        ("Degree", "degree_level"),
        ("What is your current or most recently completed degree type?", education.MIXED_KEY),
        ("If Other, please list the school name", None),
        ("Completed coursework", None),
        ("The highest degree of integrity and confidentiality", None),
        ("Highest degree you have earned and field of study", None),
    ],
)
def test_question_sources(label, key):
    match = questions.classify(questions.Question(label))
    assert (match.key if match else None) == key


def test_help_and_stale_ats_hint_cannot_override_completed_semantics():
    facts = questions.facts_for({education.KEY: "High school diploma", "degree_level": "Bachelors"})
    items = [
        dict(qid="completed", label="Highest degree", attr_key="degree_level", kind="text"),
        dict(
            qid="mixed",
            label="Highest degree",
            kind="text",
            help="For most recent or in progress degree.",
        ),
        dict(
            qid="excluded",
            label="Highest degree",
            kind="text",
            help="Do not include degrees in progress.",
        ),
    ]
    plan = questions.plan_for(items, facts)
    assert plan["completed"] == {"key": education.KEY, "value": ""}
    assert plan["mixed"] == {"key": education.MIXED_KEY, "value": "Bachelors"}
    assert plan["excluded"]["key"] == education.KEY


@pytest.mark.parametrize(
    "value,options,expected",
    [
        ("High school diploma", ["HS", "Bachelor's degree"], "HS"),
        ("GED", ["High school diploma", "GED or equivalent"], "GED or equivalent"),
        ("GED", ["High school diploma"], None),
        ("GED", ["GED and Bachelor's degree"], None),
        ("High school diploma", ["High school or GED"], "High school or GED"),
        ("Some college—no degree", ["Some college", "Bachelor's degree"], "Some college"),
        ("Bachelors", ["Bachelor's Degree", "Master's Degree"], "Bachelor's Degree"),
        ("Bachelors", ["BA", "BS"], None),
        ("Bachelors", ["Bachelor's in progress"], None),
        ("Bachelor of Science", ["BS", "BA"], "BS"),
        ("Doctorate", ["MD", "PhD"], None),
        ("Professional degree", ["Doctorate"], None),
        (
            "Higher National Diploma",
            ["Higher National Diploma", "Bachelors"],
            "Higher National Diploma",
        ),
        ("Bachelors", ["Bachelor's Degree", "BACHELOR'S DEGREE"], None),
    ],
)
def test_conservative_education_matching(value, options, expected):
    assert field_matcher.closest_option(options, value, key=education.KEY) == expected


def test_opaque_option_value_cannot_hide_in_progress_qualification():
    option = ObservedOption(option_id="1", label="Bachelor's in progress", value="Bachelors")
    assert field_matcher.match_option([option], "Bachelors", key=education.KEY).status == "no_match"


def test_blank_never_uses_in_progress_degree_or_model_classifier():
    items = [dict(qid="degree", label="Highest degree", kind="choice", options=["HS", "BS"])]

    def forbidden(_questions):
        pytest.fail("Education must not go to the model classifier")

    plan = questions.plan_for(
        items, questions.facts_for({"degree_level": "Bachelors"}), classifier=forbidden
    )
    assert plan == {"degree": {"key": education.KEY, "value": ""}}


def test_no_match_plan_explicitly_blocks_dom_fallback():
    plan = questions.plan_for(
        [dict(qid="degree", label="Highest degree", kind="choice", options=["BA", "BS"])],
        questions.facts_for({education.KEY: "Bachelors", "degree_name": "Bachelor of Science"}),
    )
    assert plan["degree"] == {"key": education.KEY, "value": None}


def test_custom_other_and_only_qualification_followup():
    fields = {}
    education.refresh_fields(fields, "Higher National Diploma")
    question = questions.Question("Highest degree", kind="choice", options=("Other", "Bachelors"))
    match = questions.classify(question)
    assert (
        questions.choose(
            question, match.key, questions.answers(match, question, questions.facts_for(fields))
        )
        == "Other"
    )
    assert education.question_key("If Other, specify your qualification") == education.DETAIL_KEY
    assert education.question_key("If Other, please list the school name") is None


def test_mixed_question_falls_back_to_completed_without_resume_degree():
    match = questions.Match(education.MIXED_KEY)
    facts = questions.facts_for({education.KEY: "High school diploma"})
    assert questions.answers(
        match, questions.Question("Highest degree or currently pursuing"), facts
    ) == ["High school diploma"]


def test_packet_fields_and_old_fill_packets_use_latest_profile():
    profile = ApplicantProfile(highest_education_obtained="GED")
    assert packet_fields.build_fields(profile, synthetic_resume())[education.KEY] == "GED"
    state = object.__new__(fill_state._FillState)
    state.app = SimpleNamespace(role="Intern", salary="")
    state.pkt = SimpleNamespace(fields={education.KEY: "Bachelors"}, education=[])
    state.profile = profile
    state.jd_text = ""
    assert state._build_fields()[education.KEY] == "GED"
    assert state.pkt.fields[education.KEY] == "GED"
    state.profile = ApplicantProfile()
    assert education.KEY not in state._build_fields()
    assert education.KEY not in state.pkt.fields


def test_profile_corrections_and_duplicates_use_completed_field(monkeypatch):
    label = "What is the highest level of education that you have completed?"
    profile = ApplicantProfile(custom_answers={label: "Bachelors"})
    assert answer_memory.profile_key(label) == education.KEY
    assert answer_memory.profile_key("Highest degree and field of study") is None
    assert not answer_memory.storable(label)
    assert custom_answers.merge(profile, label).highest_education_obtained == "Bachelors"
    assert custom_answers.target("Highest degree completed or currently pursuing") is None
    saved = []
    from resume_tailor.apply.answers import profile as profile_mod

    monkeypatch.setattr(profile_mod, "load_profile", lambda: (ApplicantProfile(), False))
    monkeypatch.setattr(profile_mod, "save_profile", saved.append)
    assert answer_memory.save_to_profile(education.KEY, "GED")
    assert saved[0].highest_education_obtained == "GED"
    assert packet_profile_fields.profile_path("Education", education.KEY) == "/profile/application"
    assert "Highest education completed: GED" in answer_facts.profile_facts(saved[0])
    assert answer._profile_answer(label, saved[0]) == "GED"


def test_verified_catalog_uses_helper_and_overrides_generic_hint():
    field = FieldObservation(
        snapshot_id="s",
        field_id="f",
        frame_id="main",
        document_generation="1",
        label="Highest degree",
        canonical_key="degree_level",
        control_kind="native_select",
    )
    assert field_catalog.classify(field) == ("known", education.KEY)
    field.help_text = "For the degree currently pursuing."
    assert field_catalog.classify(field) == ("known", education.MIXED_KEY)
    field.help_text = ""
    field.options = [
        ObservedOption(option_id=str(i), label=label) for i, label in enumerate(["Yes", "No"])
    ]
    assert field_catalog.classify(field)[0] == "manual_review"


def test_hybrid_never_recalls_or_asks_model_for_reserved_education(monkeypatch):
    field = dict(
        label="Highest degree", selector="#degree", type="radiogroup", options=["BS", "HS"]
    )
    from resume_tailor.apply.answers import page_blockers

    monkeypatch.setattr(
        page_blockers,
        "extract_page_blockers",
        lambda _page: dict(
            errors=[],
            unresolved=[field],
            advance_disabled=True,
        ),
    )
    monkeypatch.setattr(
        hybrid_resolver._StepResolver,
        "_answer",
        lambda *_args: pytest.fail("Reserved question reached cached/model answers"),
    )
    pkt = packet_models.Packet(job_id="j", built_at="now", posting_url="https://example.com")
    assert not hybrid_resolver.resolve_step_blockers(
        object(), pkt, ApplicantProfile(), max_retries=1
    )
