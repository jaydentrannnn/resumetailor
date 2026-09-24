"""Pure Apply field contracts: source facts, choice matching and manual policies."""

from __future__ import annotations

import pytest

from resume_tailor.apply.field_catalog import classify
from resume_tailor.apply.field_matcher import match_option, match_skill_option
from resume_tailor.apply.field_types import FieldObservation, FieldOutcome, ObservedOption
from resume_tailor.apply.preparation import PreparedExpansion
from resume_tailor.apply.engine import _availability_for_field, _current_outcome, _national_phone_value
from resume_tailor.apply.controls import _phone_match


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


def test_combined_sponsorship_and_current_are_distinct():
    assert classify(observation("Do you now or in the future require sponsorship?")) == ("known", "requires_sponsorship_any")
    assert classify(observation("Do you currently require sponsorship?")) == ("known", "requires_sponsorship")


def test_empty_prepared_experience_requires_durable_source_evidence():
    assert PreparedExpansion(entries=[]).status == "missing"
    assert PreparedExpansion(entries=[], source_experience_count=0).status == "not_applicable"


def test_authentication_controls_are_not_profile_fields():
    assert classify(observation("Password", input_type="password")) == ("manual_review", "credential_or_verification")
    assert classify(observation("Verification code", autocomplete="one-time-code")) == ("manual_review", "credential_or_verification")


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
