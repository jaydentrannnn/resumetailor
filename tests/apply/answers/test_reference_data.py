"""Option lists the Profile pickers use, and the matching built on them."""

from resume_tailor.apply.answers import reference_data
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import ObservedOption


def _options(*labels: str) -> list[ObservedOption]:
    return [ObservedOption(option_id=str(i), label=label, value=label) for i, label in enumerate(labels)]


def test_country_lookup_by_alias_and_label():
    assert reference_data.country("USA")["name"] == "United States"
    assert reference_data.country("uk")["dial"] == "+44"
    assert reference_data.phone_label("+1", "United States") == "United States (+1)"


def test_state_code_and_name_round_trip():
    assert reference_data.state_code("California") == "CA"
    assert reference_data.state_name("ca") == "California"
    assert reference_data.state_code("Ontario", "Canada") == "ON"
    assert reference_data.state_code("Nowhere") == ""


def test_blank_phone_region_defaults_from_the_dial_code():
    assert ApplicantProfile().phone_country_region == "United States"
    uk = ApplicantProfile.model_validate({"phone_country_code": "+44", "country": "United Kingdom"})
    assert uk.phone_country_region == "United Kingdom"
    kept = ApplicantProfile.model_validate({"phone_country_code": "+1", "phone_country_region": "Canada"})
    assert kept.phone_country_region == "Canada"


def test_state_and_country_match_other_spellings():
    assert match_option(_options("AL", "CA"), "California", key="state").option_id == "1"
    assert match_option(_options("Alabama", "California"), "CA", key="state").option_id == "1"
    assert match_option(_options("USA", "Canada"), "United States", key="country").option_id == "0"


def test_non_binary_gender_option_matches():
    result = match_option(_options("Male", "Female", "Non-binary"), "Non-binary", key="gender")
    assert (result.status, result.option_id) == ("matched", "2")
