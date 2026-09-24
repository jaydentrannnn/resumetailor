"""Pure Apply field contracts: source facts, choice matching and manual policies."""

from __future__ import annotations

import pytest

from resume_tailor.apply.field_catalog import classify
from resume_tailor.apply.field_matcher import (
    choice_values, closest_option, degree_of, eeo_patterns, fallback_values, match_option,
    match_skill_option, search_terms,
)
from resume_tailor.apply.field_types import FieldObservation, FieldOutcome, ObservedOption
from resume_tailor.apply.preparation import PreparedExpansion
from resume_tailor.apply.engine import _availability_for_field, _current_outcome, _national_phone_value
from resume_tailor.apply.controls import _phone_match
from resume_tailor.apply.adapters import GreenhouseAdapter, WorkdayAdapter
from resume_tailor.apply.packet import Packet, PacketEducation


def option(label: str, *, value: str = "", disabled: bool = False) -> ObservedOption:
    return ObservedOption(option_id=label, label=label, value=value, enabled=not disabled)


def observation(label: str, *, section: str = "", kind: str = "text", **constraints):
    return FieldObservation(
        snapshot_id="one", field_id=label, frame_id="main", document_generation="1",
        label=label, section_id=section, control_kind=kind, constraints=constraints,
    )


def test_exact_matching_rejects_ambiguous_aliases_and_misleading_substrings():
    options = [option("Not applicable"), option("No"), option("No", value="second")]
    assert match_option(options, "No").status == "ambiguous"
    assert match_option(options[:1], "No").status == "no_match"
    assert match_option([option("Not applicable"), option("No", disabled=True)], "No").status == "no_match"
    assert match_option([option("US", value="us"), option("Canada")], "United States", key="country").option_id == "US"


def test_manual_and_contextual_field_classification():
    # Salary is a deterministic per-posting answer (`apply/salary.py`), in the unit asked for.
    assert classify(observation("Desired salary")) == ("known", "salary_expectation")
    assert classify(observation("Desired hourly pay rate")) == ("known", "salary_hourly")
    assert classify(observation("Certification of accuracy"))[0] == "manual_review"
    assert classify(observation("Start date", section="Work Experience"))[0] == "unknown"
    assert classify(observation("When can you start?")) == ("known", "earliest_start")
    assert classify(observation("Country", section="Phone", kind="combobox", phone_sibling=True)) == ("known", "phone_country_code")
    assert classify(observation("Country", section="Address", kind="combobox")) == ("known", "country")
    assert classify(observation("Are you Hispanic/Latino?")) == ("known", "hispanic_latino")
    assert classify(observation("First Name", section="Preferred Name")) == ("known", "preferred_name")
    assert classify(observation("Last Name", section="Preferred Name")) == ("known", "last_name")
    assert classify(observation("First Name", section="Legal Name")) == ("known", "first_name")
    assert classify(observation("First Year Attended", section="Education")) == ("known", "education_start_year")


def test_eligibility_questions_are_not_the_country_field():
    permitted = "Are you legally permitted to work in the country where this job is located?"
    assert classify(observation(permitted, kind="combobox")) == ("known", "authorized_to_work")
    assert classify(observation("If hired, can you provide proof of eligibility?", kind="combobox")) == ("known", "authorized_to_work")
    assert classify(observation("Are you over the age of 18?", kind="combobox")) == ("known", "over_18")
    assert classify(observation("Are you under 18?", kind="combobox"))[1] != "over_18"
    # Sponsorship wording keeps its own key.
    assert classify(observation("Are you authorized to work without sponsorship?")) == ("known", "requires_sponsorship")


def test_combined_sponsorship_and_current_are_distinct():
    assert classify(observation("Do you now or in the future require sponsorship?")) == ("known", "requires_sponsorship_any")
    assert classify(observation("Do you currently require sponsorship?")) == ("known", "requires_sponsorship")


def test_empty_prepared_experience_requires_durable_source_evidence():
    assert PreparedExpansion(entries=[]).status == "missing"
    assert PreparedExpansion(entries=[], source_experience_count=0).status == "not_applicable"


def test_authentication_controls_are_not_profile_fields():
    assert classify(observation("Password", input_type="password")) == ("manual_review", "credential_or_verification")
    assert classify(observation("Verification code", autocomplete="one-time-code")) == ("manual_review", "credential_or_verification")


def test_education_year_is_scoped_to_its_row():
    packet = Packet(job_id="test", built_at="2026-01-01T00:00:00Z", education=[
        PacketEducation(school="Test University", start="2023-09", end="2027-06"),
    ])
    field = observation("Start Year", section="Education", id="start-year--0")
    field.repeater_row_id = "0"
    adapter = GreenhouseAdapter()
    assert adapter.classify(field) == ("known", "education_start_year")
    assert adapter.value_for(field, "education_start_year", packet, {}) == "2023"
    field.constraints["id"] = "education-1--firstYearAttended"
    assert WorkdayAdapter().value_for(field, "education_start_year", packet, {}) == "2023"


def test_phone_prefix_is_removed_only_with_a_committed_same_group_code():
    assert _national_phone_value("+1 (555) 123-4567", "+1", separate_code_committed=True) == "(555) 123-4567"
    assert _national_phone_value("+1 (555) 123-4567", "+1", separate_code_committed=False) == "+1 (555) 123-4567"


def test_phone_region_can_match_a_declared_country_identifier():
    options = [option("United States", value="US"), option("Canada", value="CA")]
    assert _phone_match(options, "+1", "United States") == options[0]
    assert _phone_match(options, "+1", "") is None


def test_availability_formats_only_text_question_not_native_date_input():
    assert _availability_for_field("2027-06-14", "text") == "June 14, 2027"
    assert _availability_for_field("2027-06-14", "date") == "2027-06-14"


def test_handoff_rechecks_retained_values_and_manual_policy():
    school = observation("School", kind="combobox")
    school.current_value = "UC Irvine"
    school.selection_state = "committed"
    earlier = FieldOutcome(field_id=school.field_id, state="verified_filled", observed_value="UC Irvine", answer_source="profile")
    assert _current_outcome(school, earlier).state == "verified_filled"
    school.current_value = "Irvine"
    school.selection_state = "typed"
    assert _current_outcome(school, earlier).state == "unanswered"
    school.current_value = "University of California, Irvine"
    school.selection_state = "committed"
    assert _current_outcome(school, earlier).state == "preserved"
    school.validation_messages = ["Choose a listed school"]
    assert _current_outcome(school, earlier).state == "invalid_existing"

    salary = observation("Desired salary")
    salary.current_value = "50,000"
    assert _current_outcome(salary, None).state == "preserved"


@pytest.mark.parametrize(
    ("options", "skill", "expected"),
    [
        # An abbreviation picks the option that spells it out, and the reverse.
        (["Retrieval-Augmented Generation (RAG)", "Ragtime"], "RAG", "Retrieval-Augmented Generation (RAG)"),
        (["RAG", "Generation"], "Retrieval-Augmented Generation (RAG)", "RAG"),
        (["Retrieval Augmented Generation (RAG)"], "Retrieval-Augmented Generation", "Retrieval Augmented Generation (RAG)"),
        # Exact text wins over an abbreviation match.
        (["Python", "Python (Programming Language)"], "Python", "Python"),
        (["Python (Programming Language)", "Django"], "Python", "Python (Programming Language)"),
        # One skill listed under two categories is one answer.
        (["SQL", "SQL"], "sql", "SQL"),
        # C# is not C, .NET is not NET.
        (["C", "C++"], "C#", None),
        (["C#", "C"], "C#", "C#"),
        # Never a partial or substring match, and a tie is no answer.
        (["Data Analytics", "Data Analysis Tools"], "data analysis", None),
        (["Machine Learning (ML)", "ML (Markup Language)"], "ML", None),
        ([], "Python", None),
    ],
)
def test_match_skill_option(options, skill, expected):
    assert match_skill_option(options, skill) == expected


def test_school_search_terms_fall_back_to_the_campus():
    # Workday's school search finds nothing for the full name typed with its dash.
    terms = search_terms("school", "University of California - Irvine")
    assert terms[0] == "University of California - Irvine"
    assert "Irvine" in terms
    assert search_terms("school", "California State University, Long Beach")[1] == "Long Beach"
    assert search_terms("school", "University of Wisconsin at Madison")[1] == "Madison"
    assert search_terms("major", "Computer Science") == ["Computer Science"]
    assert search_terms("degree_level", "Bachelors")[0] == "bachelor"
    assert search_terms("school", "  ") == []


def test_closest_option_accepts_one_decorated_option_and_rejects_ties():
    options = ["University of California, Irvine", "Irvine Valley College"]
    assert closest_option(options, "University of California - Irvine", key="school") == options[0]
    decorated = ["University of California Irvine (UCI)", "Irvine Valley College"]
    assert closest_option(decorated, "University of California - Irvine", key="school") == decorated[0]
    tie = ["University of California Irvine (UCI)", "University of California Irvine Extension"]
    assert closest_option(tie, "University of California - Irvine", key="school") is None
    # Containment is only for decorated-answer keys: a country is never a "closest" guess.
    countries = ["United States Minor Outlying Islands", "Canada"]
    assert closest_option(countries, "United States", key="country") is None


@pytest.mark.parametrize(("text", "expected"), [
    ("BS", ("bachelor", "bachelor of science")),
    ("B.S.", ("bachelor", "bachelor of science")),
    ("BSc", ("bachelor", "bachelor of science")),
    ("Bachelor of Science (B.S)", ("bachelor", "bachelor of science")),
    ("Bachelor's Degree (BS)", ("bachelor", "bachelor of science")),
    ("BS Computer Science", ("bachelor", "bachelor of science")),
    ("Bachelor of Science in Computer Science & Minor in Business Management",
     ("bachelor", "bachelor of science")),
    ("B.S.E.", ("bachelor", "bachelor of science in engineering")),
    ("Bachelor of Science in Engineering", ("bachelor", "bachelor of science in engineering")),
    ("BA", ("bachelor", "bachelor of arts")),
    ("M.S.", ("master", "master of science")),
    ("Ph.D.", ("doctor", "doctor of philosophy")),
    ("Bachelor's Degree", ("bachelor", "")),
    ("Bachelors", ("bachelor", "")),
    ("Bachelor's Degree (BA/BS)", ("bachelor", "")),
    ("High School Diploma", None),
    ("Business", None),
])
def test_degree_of_reads_names_and_abbreviations(text, expected):
    assert degree_of(text) == expected


def test_a_named_degree_matches_its_abbreviation_then_the_bare_level():
    abbreviations = [option("Select One"), option("HS"), option("BA"), option("BS"), option("MS")]
    assert match_option(abbreviations, "Bachelor of Science", key="degree_level").option_id == "BS"
    assert match_option(abbreviations, "BS Computer Science", key="degree_level").option_id == "BS"
    dotted = [option("B.A."), option("B.S."), option("M.S.")]
    assert match_option(dotted, "Bachelor of Science", key="degree_level").option_id == "B.S."
    levels = [option("Associate's Degree"), option("Bachelor's Degree"), option("Master's Degree")]
    assert match_option(levels, "Bachelor of Science", key="degree_level").option_id == "Bachelor's Degree"
    # A bare level cannot choose between the BS and the BA; the key gates the rule.
    assert match_option(abbreviations, "Bachelors", key="degree_level").status == "no_match"
    assert match_option(abbreviations, "Bachelor of Science", key="major").status == "no_match"
    both = [option("BS"), option("Bachelor of Science")]
    assert match_option(both, "B.Sc.", key="degree_level").status == "ambiguous"


def test_choice_values_try_the_named_degree_before_the_level():
    fields = {"degree_level": "Bachelors", "degree_name": "Bachelor of Science"}
    assert choice_values("degree_level", fields) == ["Bachelor of Science", "Bachelors"]
    assert choice_values("degree_level", {"degree_level": "Bachelors"}) == ["Bachelors"]
    assert choice_values("race", {"race": "Asian", "race_detail": "Southeast Asian"}) == ["Southeast Asian", "Asian"]
    assert choice_values("how_heard", {"how_heard": "LinkedIn"}) == ["LinkedIn", "Other"]
    assert "BS" in search_terms("degree_level", "Bachelor of Science")


def test_how_heard_falls_back_to_other():
    assert fallback_values("how_heard", "LinkedIn") == ["LinkedIn", "Other"]
    assert fallback_values("how_heard", "Other") == ["Other"]
    assert fallback_values("gender", "Decline") == ["Decline"]
    assert fallback_values("how_heard", "") == []


_DISABILITY = ["Yes, I have a disability, or have had one in the past",
               "No, I do not have a disability and have not had one in the past", "I do not want to answer"]
_VETERAN = ["I am not a protected veteran",
            "I identify as one or more of the classifications of protected veteran", "I don't wish to answer"]

_CACI_VETERAN = ["I IDENTIFY AS ONE OR MORE OF THE CLASSIFICATIONS OF PROTECTED VETERANS",
                 "I IDENTIFY AS A VETERAN, JUST NOT A PROTECTED VETERAN", "I AM NOT A VETERAN",
                 "I DO NOT WISH TO SELF-IDENTIFY"]


@pytest.mark.parametrize(("key", "options", "answer", "expected"), [
    ("disability_status", _DISABILITY, "Yes", 0),
    ("disability_status", _DISABILITY, "No", 1),
    ("disability_status", _DISABILITY, "decline", 2),
    ("veteran_status", _VETERAN, "No", 0),
    ("veteran_status", _VETERAN, "Yes", 1),
    ("veteran_status", _VETERAN, "decline", 2),
    # CACI (2026-09): "No" is the non-veteran, not the veteran who is not protected.
    ("veteran_status", _CACI_VETERAN, "No", 2),
    ("veteran_status", _CACI_VETERAN, "Yes", 0),
    ("veteran_status", _CACI_VETERAN, "decline", 3),
    ("gender", ["Male", "Female", "Decline to Self Identify"], "decline", 2),
    ("race", ["Asian (United States of America)", "White (United States of America)"], "Asian", 0),
    ("hispanic_latino", ["Hispanic or Latino", "Not Hispanic or Latino"], "No", 1),
    ("hispanic_latino", ["Hispanic or Latino", "Not Hispanic or Latino"], "Yes", 0),
])
def test_self_identification_answers_pick_the_long_form_option(key, options, answer, expected):
    assert closest_option(options, answer, key=key) == options[expected]


def test_self_identification_never_guesses():
    # No decline option, a prefix shared by two options, and a key that is not EEO.
    assert closest_option(_DISABILITY[:2], "decline", key="disability_status") is None
    assert closest_option(["Asian", "Asian Indian"], "Asia", key="race") is None
    assert closest_option(_DISABILITY, "No", key="city") is None
    assert eeo_patterns({"gender": "", "veteran_status": "No", "city": "Irvine"}).keys() == {"veteran_status"}


@pytest.mark.parametrize(("options", "answer", "expected"), [
    (["Beginner", "Intermediate", "Advanced", "Fluent"], "Advanced", "Advanced"),
    # No native rank on this scale: the highest rank below it, never above.
    (["Beginner", "Intermediate", "Advanced", "Fluent"], "Native", "Fluent"),
    (["Elementary proficiency", "Limited working proficiency", "Professional working proficiency",
      "Full professional proficiency", "Native or bilingual proficiency"], "Intermediate", "Limited working proficiency"),
    (["Intermediate", "Advanced"], "Beginner", None),
])
def test_language_levels_match_by_rank(options, answer, expected):
    assert closest_option(options, answer, key="language_level") == expected
