"""Answer memory: corrections remembered and reused by later fills (plan P3-A)."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply import answer_memory as memory


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")


@pytest.mark.parametrize(
    ("label", "company", "expected"),
    [
        ("Why do you want to work at Acme?", "Acme", "why do you want to work at {company}"),
        ("Why do you want to work at ACME?", "Acme Inc.", "why do you want to work at {company}"),
        ("  How did you   hear about us?? ", "", "how did you hear about us"),
        ("Are you 18+ (yes/no)?", "Acme", "are you 18 yes no"),
        # Only whole words: "Acmeology" is not the company.
        ("Describe Acmeology", "Acme", "describe acmeology"),
    ],
)
def test_normalize_label(label, company, expected):
    assert memory.normalize_label(label, company) == expected


def test_company_name_drops_legal_suffixes():
    assert memory.company_name("Acme Corp.") == "Acme"
    assert memory.company_name("Beta Holdings, LLC") == "Beta"
    assert memory.company_name("") == ""


def test_a_correction_is_reused_for_the_same_question_elsewhere():
    memory.remember(
        "How did you hear about us?", "University career fair", company="Acme", ats="greenhouse"
    )
    recalled = memory.recall("How did you hear about us", company="Beta", ats="lever")
    assert recalled is not None and not recalled.needs_review
    assert recalled.answer == "University career fair"
    assert memory.list_answers()[0].uses == 1


def test_same_ats_answer_wins_over_another_ats():
    memory.remember("Preferred office", "Remote", ats="greenhouse")
    memory.remember("Preferred office", "New York", ats="workday")
    assert memory.recall("Preferred office", ats="workday").answer == "New York"
    assert memory.recall("Preferred office", ats="greenhouse").answer == "Remote"
    # Unknown ATS: the most recently updated row.
    assert memory.recall("Preferred office", ats="ashby").answer == "New York"


def test_company_specific_answer_is_flagged_not_reused_for_another_company():
    memory.remember("Why Acme?", "I have followed Acme's work on payments.", company="Acme Inc")
    same = memory.recall("Why Acme?", company="Acme")
    assert same is not None and not same.needs_review
    other = memory.recall("Why Beta?", company="Beta")
    assert other is not None and other.needs_review
    assert "Acme" in other.reason
    # A generic answer to the same templated question is fine anywhere.
    memory.remember("Why Acme?", "The internship matches my coursework.", company="Acme")
    assert not memory.recall("Why Beta?", company="Beta").needs_review


@pytest.mark.parametrize(
    ("label", "kwargs"),
    [
        ("Gender", {}),
        ("Are you a protected veteran?", {}),
        ("Please select your race/ethnicity", {}),
        ("Disability status", {}),
        ("Which option describes you?", {"canonical_key": "gender"}),
        ("Enter the verification code we emailed", {}),
        ("Create a password", {}),
        ("Account", {"input_type": "password"}),
        ("Social Security Number", {}),
        ("Date of birth", {}),
    ],
)
def test_sensitive_answers_are_never_stored(label, kwargs):
    assert memory.remember(label, "something", **kwargs) is None
    assert memory.list_answers() == []
    assert memory.recall(label, **{k: v for k, v in kwargs.items() if k == "canonical_key"}) is None


def test_a_second_correction_replaces_the_first():
    memory.remember("Earliest start date?", "June 2026")
    memory.remember("Earliest start date", "May 2026")
    saved = memory.list_answers()
    assert [s.answer for s in saved] == ["May 2026"]


def test_edit_and_delete():
    saved = memory.remember("Portfolio link", "https://example.com")
    edited = memory.update(saved.id, "https://example.org")
    assert edited.answer == "https://example.org" and edited.source == "edited"
    with pytest.raises(ValueError):
        memory.update(saved.id, "   ")
    memory.delete(saved.id)
    assert memory.list_answers() == []
    with pytest.raises(KeyError):
        memory.delete(saved.id)
    with pytest.raises(KeyError):
        memory.update(saved.id, "x")


def test_blank_or_oversized_answers_are_ignored():
    assert memory.remember("Anything else?", "  ") is None
    assert memory.remember("Anything else?", "x" * (memory.MAX_ANSWER_CHARS + 1)) is None
