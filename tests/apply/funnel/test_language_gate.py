"""Spoken-language requirements in the no-LLM prefilter (`language_gate`)."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import profile
from resume_tailor.apply.answers.profile import LanguageEntry
from resume_tailor.apply.funnel import daily_rows, language_gate, screen
from resume_tailor.web.schemas import ApplySettings


def _langs(*entries: tuple[str, bool]) -> list[LanguageEntry]:
    return [LanguageEntry(language=name, fluent=fluent) for name, fluent in entries]


SPANISH_REQUIRED = "Requirements:\n- Fluent in Spanish and English (required).\n- SQL."


def test_a_required_language_the_profile_lacks_is_a_reason_with_its_sentence():
    reasons, flags, evidence = language_gate.check(SPANISH_REQUIRED, _langs(("English", True)))
    assert (reasons, flags) == (["language_required:Spanish"], [])
    assert evidence == ["- Fluent in Spanish and English (required)."]
    assert screen.screen_label(reasons) == "Spanish required"


def test_a_listed_language_passes_and_a_not_fluent_one_is_only_flagged():
    assert language_gate.check(SPANISH_REQUIRED, _langs(("Spanish (native)", True))) == ([], [], [])
    assert language_gate.check(SPANISH_REQUIRED, _langs(("spanish", False))) == (
        [], ["language_level:Spanish"], []
    )
    # "Must speak" asks for the language, not a level, so not-fluent is enough.
    assert language_gate.check("You must speak Spanish with clients.", _langs(("Spanish", False))) == (
        [], [], []
    )


def test_a_profile_without_languages_is_flagged_never_rejected():
    assert language_gate.check(SPANISH_REQUIRED, []) == ([], ["language_unlisted:Spanish"], [])
    assert language_gate.check(SPANISH_REQUIRED, None) == ([], [], [])


def test_english_is_assumed_unless_listed_as_not_fluent():
    english = "Must be fluent in English."
    assert language_gate.check(english, []) == ([], [], [])
    assert language_gate.check(english, _langs(("Korean", True))) == ([], [], [])
    assert language_gate.check(english, _langs(("English", False))) == (
        [], ["language_level:English"], []
    )


@pytest.mark.parametrize(
    "text",
    [
        "Fluency in Spanish is a plus.",
        "Bilingual (English/Spanish) preferred.",
        "Spanish speakers are encouraged to apply.",
        "Preferred Qualifications\n- Fluent in Japanese\n- AWS",
        "We serve Spanish-speaking communities across the region.",
        "Proficiency in SQL and Excel.\nOur Spanish team is growing.",
        "Polish the UI until it is fluent and fast.",
        "Build cloud-native Python services; our office is in Tokyo with Japanese clients.",
        "It is mandatory to be enrolled at a Dutch university.",
    ],
)
def test_optional_or_incidental_mentions_never_count(text):
    assert language_gate.check(text, _langs(("English", True))) == ([], [], [])


def test_a_required_heading_after_an_optional_one_counts_again():
    text = "Preferred qualifications:\n- Go\nBasic Qualifications:\n- Fluent German"
    assert language_gate.check(text, _langs(("English", True)))[0] == ["language_required:German"]


def test_alternatives_are_satisfied_by_any_one():
    either = "Must be fluent in Spanish or Portuguese."
    assert language_gate.check(either, _langs(("Portuguese", True))) == ([], [], [])
    assert language_gate.check(either, _langs(("French", True)))[0] == [
        "language_required:Spanish or Portuguese"
    ]
    both = "Must be fluent in Spanish and Portuguese."
    assert language_gate.check(both, _langs(("Portuguese", True)))[0] == [
        "language_required:Spanish"
    ]


def test_chinese_varieties_and_aliases():
    assert language_gate.check("Fluent Mandarin required.", _langs(("Chinese", True))) == ([], [], [])
    assert language_gate.check("Fluent Chinese required.", _langs(("Cantonese", True))) == ([], [], [])
    assert language_gate.check("Fluent Cantonese required.", _langs(("Mandarin", True)))[0] == [
        "language_required:Cantonese"
    ]
    assert language_gate.check("Business-level Farsi required.", _langs(("Persian", True))) == (
        [], [], []
    )


def test_prefilter_reads_the_profile_languages(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    settings = ApplySettings()
    flagged = daily_rows.prefilter_screen(SPANISH_REQUIRED, "Analyst", settings)
    assert flagged.passed and "language_unlisted:Spanish" in flagged.flags
    config.APPLICANT_PROFILE_PATH.write_text(
        json.dumps({"languages": [{"language": "English", "fluent": True}]}), "utf-8"
    )
    rejected = daily_rows.prefilter_screen(SPANISH_REQUIRED, "Analyst", settings)
    assert not rejected.passed and rejected.reasons == ["language_required:Spanish"]
    assert rejected.evidence == ["- Fluent in Spanish and English (required)."]
    config.APPLICANT_PROFILE_PATH.write_text("{not json", "utf-8")
    assert profile.load_languages() is None
    assert daily_rows.prefilter_screen(SPANISH_REQUIRED, "Analyst", settings).passed
