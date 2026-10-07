"""Answer memory: corrections remembered and reused by later fills (plan P3-A)."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import answer_memory as memory


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")


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
        "Which team interests you most?", "Payments", company="Acme", ats="greenhouse"
    )
    recalled = memory.recall("Which team interests you most", company="Beta", ats="lever")
    assert recalled is not None and not recalled.needs_review
    assert recalled.answer == "Payments"
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
    memory.remember("Preferred team?", "Risk")
    memory.remember("Preferred team", "Payments")
    saved = memory.list_answers()
    assert [s.answer for s in saved] == ["Payments"]


def test_edit_and_delete():
    saved = memory.remember("Favorite product of ours", "The API")
    edited = memory.update(saved.id, "The dashboard")
    assert edited.answer == "The dashboard" and edited.source == "edited"
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


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Middle Name", "middle_name"),
        ("How did you hear about us?", "how_heard"),
        ("Address Line 2", "address_line2"),
        ("LinkedIn Profile URL", "linkedin_url"),
        ("Who referred you?", "referred_by"),
    ],
)
def test_profile_questions_are_not_remembered(label, key):
    assert memory.profile_key(label) == key
    assert memory.remember(label, "something") is None
    assert memory.list_answers() == []


def test_long_questions_that_mention_a_profile_word_are_remembered():
    label = "Describe a project from school that you are proud of and what you learned"
    assert memory.profile_key(label) is None
    assert memory.remember(label, "The compiler") is not None


def test_a_profile_correction_fills_only_a_blank_profile_field():
    from resume_tailor.apply.answers import profile as profile_mod

    assert memory.save_to_profile("middle_name", "Quinn")
    assert profile_mod.load_profile()[0].middle_name == "Quinn"
    # The profile is the source: a field that holds a value is not overwritten.
    assert not memory.save_to_profile("middle_name", "Other")
    assert profile_mod.load_profile()[0].middle_name == "Quinn"
    # Non-text fields (Yes/No, EEO) are never written from a correction.
    assert not memory.save_to_profile("gender", "Decline")


def _insert(label: str, answer: str, ats: str, updated_at: str) -> None:
    """A row as an earlier version stored it, bypassing today's filter."""
    conn = memory._conn()  # noqa: SLF001
    with memory.db.transaction(conn):
        conn.execute(
            "INSERT INTO answer_memory(label_norm, ats, label, answer, company, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, '', 'correction', ?, ?)",
            (memory.normalize_label(label), ats, label, answer, updated_at, updated_at),
        )


def test_answers_are_listed_once_per_question_with_their_sites():
    memory.db.set_marker(memory._conn(), memory.CLEANUP_MARKER)  # noqa: SLF001
    _insert("Preferred office", "Remote", "greenhouse", "2026-01-01T00:00:00+00:00")
    _insert("Preferred office", "New York", "workday", "2026-02-01T00:00:00+00:00")
    _insert("Favorite product", "The API", "lever", "2026-01-15T00:00:00+00:00")
    listed = memory.list_answers()
    assert [(a.label, a.answer, a.sites, a.differs) for a in listed] == [
        ("Preferred office", "New York", ["greenhouse", "workday"], True),
        ("Favorite product", "The API", ["lever"], False),
    ]
    # Edit and delete act on the question, on every site.
    memory.update(listed[0].id, "Hybrid")
    assert {memory.recall("Preferred office", ats=ats).answer for ats in ("greenhouse", "workday")} == {"Hybrid"}
    memory.delete(listed[0].id)
    assert [a.label for a in memory.list_answers()] == ["Favorite product"]


def test_cleanup_moves_profile_duplicates_out_once_with_a_backup(tmp_path):
    from resume_tailor.apply.answers import profile as profile_mod

    _insert("Middle Name", "Quinn", "workday", "2026-02-01T00:00:00+00:00")
    _insert("Middle name", "Old", "greenhouse", "2026-01-01T00:00:00+00:00")
    _insert("How did you hear about us?", "Career fair", "workday", "2026-01-01T00:00:00+00:00")
    _insert("Preferred office", "Remote", "workday", "2026-01-01T00:00:00+00:00")
    listed = memory.list_answers()  # runs the one-off cleanup
    assert [a.label for a in listed] == ["Preferred office"]
    profile = profile_mod.load_profile()[0]
    assert profile.middle_name == "Quinn"  # the most recent answer filled the blank field
    assert profile.how_heard != "Career fair"  # a field with a value is kept
    backups = list((tmp_path / "backups").glob("answer_memory-*.json"))
    assert len(backups) == 1 and "Career fair" in backups[0].read_text(encoding="utf-8")
    # Idempotent: a row stored after the pass is not touched again.
    _insert("Middle Name", "Later", "lever", "2026-03-01T00:00:00+00:00")
    assert memory.cleanup_profile_duplicates() == 0


def test_save_to_profile_fills_blank_yes_no_and_date_fields(tmp_path, monkeypatch):
    from resume_tailor import config
    from resume_tailor.apply.answers import profile as profile_mod

    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    profile_mod.save_profile(profile_mod.ApplicantProfile(authorized_to_work=False))

    assert memory.save_to_profile("over_18", "Yes")
    assert memory.save_to_profile("earliest_start", "June 14, 2027")
    assert memory.save_to_profile("notice_period", "2 weeks")
    assert not memory.save_to_profile("authorized_to_work", "Yes")  # already set: the profile wins
    assert not memory.save_to_profile("gender", "Male")  # self-ID is never copied

    saved, _ = profile_mod.load_profile()
    assert saved.over_18 is True
    assert saved.authorized_to_work is False
    assert saved.earliest_start == "2027-06-14"
    assert (saved.notice_period_value, saved.notice_period_unit) == (2, "week")
