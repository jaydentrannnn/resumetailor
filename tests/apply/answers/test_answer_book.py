"""The Answer book: AI picks, custom and page answers, and learned question types."""

from __future__ import annotations

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import answer_book, answer_memory, hybrid_resolver
from resume_tailor.apply.answers import profile as profile_mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    monkeypatch.setattr(config, "APPLICATIONS_PATH", tmp_path / "applications.json")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    profile_mod.save_profile(profile_mod.ApplicantProfile(first_name="Ada"))


def _ai(key, label, value, digest=None):
    current = answer_book.ai_digest(hybrid_resolver.current_digest())
    return {key: {"action": "select_combobox", "value": value, "label": label,
                  "options": ["Yes", "No"], "digest": current if digest is None else digest}}


def test_only_picks_for_the_current_profile_are_listed_and_reused():
    hybrid_resolver._write_choices(_ai("k1", "Remote ok?", "Yes") | _ai("k2", "Old", "No", "stale"))
    listed = [(a.label, a.answer, a.source) for a in answer_memory.list_answers()]
    assert listed == [("Remote ok?", "Yes", "ai")]
    assert answer_book.ai_choices(["k1", "k9"]) == {
        "k1": {"action": "select_combobox", "value": "Yes", "label": "Remote ok?"}
    }
    # A pick is not a plain answer: another form's free-text question does not get it.
    assert answer_memory.recall("Remote ok?") is None


def test_forget_and_edit_an_ai_pick():
    hybrid_resolver._write_choices(_ai("k1", "Remote ok?", "Yes"))
    [row] = answer_memory.list_answers()
    assert answer_memory.update(row.id, "No").source == "edited"
    assert answer_book.ai_choices(["k1"])["k1"]["value"] == "No"
    answer_memory.delete(row.id)
    assert answer_book.ai_choices(["k1"]) == {}


def test_older_stores_are_imported_once(tmp_path):
    profile_mod.save_profile(profile_mod.ApplicantProfile(
        first_name="Ada", custom_answers={"Which team interests you?": "Payments"},
    ))
    # The model is shown the same custom answers before and after the move, so its
    # picks for this profile stay usable.
    digest = hybrid_resolver.current_digest()
    hybrid_resolver._choices_path().write_text(json.dumps({
        "k1": {"action": "choose_radio", "value": "Yes", "label": "Travel ok?",
               "digest": digest, "version": hybrid_resolver._RESOLVER_PROMPT_VERSION},
    }), encoding="utf-8")
    rows = {(a.label, a.answer, a.source) for a in answer_memory.list_answers()}
    assert rows == {("Travel ok?", "Yes", "ai"), ("Which team interests you?", "Payments", "custom")}
    assert profile_mod.load_profile()[0].custom_answers == {}
    assert hybrid_resolver.current_digest() == digest
    assert list((tmp_path / "backups").glob("custom_answers-*.json"))
    answer_memory.delete(next(a.id for a in answer_memory.list_answers() if a.source == "ai"))
    assert len(answer_memory.list_answers()) == 1  # not imported again


def test_a_custom_answer_to_a_profile_question_fills_the_field():
    profile_mod.save_profile(profile_mod.ApplicantProfile(
        first_name="Ada", custom_answers={"Middle name": "Lovelace"},
    ))
    assert answer_memory.list_answers() == []
    assert profile_mod.load_profile()[0].middle_name == "Lovelace"


def test_recall_with_options_returns_the_offered_wording():
    answer_memory.remember("Preferred office?", "remote", source="page")
    recalled = answer_memory.recall("Preferred office?", options=["Austin", "Remote - US"])
    assert recalled is not None and recalled.answer == "Remote - US"
    assert answer_memory.recall("Preferred office?", options=["Austin", "Denver"]) is None


def test_learned_types_skip_the_model_and_never_cover_eligibility():
    options = ["Yes", "No"]
    assert answer_book.learn_type("Will you relocate to Austin?", options, "willing_to_relocate",
                                  "is willing to relocate")
    assert answer_book.learned_type("Will you relocate to Austin?", ["No", "Yes"]) == (
        "willing_to_relocate"
    )
    assert answer_book.learned_type("Will you relocate to Austin?", ["Maybe"]) is None
    for key in ("requires_sponsorship", "authorized_to_work", "noncompete", "gender"):
        assert not answer_book.learn_type("Some question?", options, key, "x")
    [row] = answer_memory.list_answers()
    assert (row.kind, row.canonical_key) == ("type", "willing_to_relocate")
    with pytest.raises(ValueError):
        answer_memory.update(row.id, "anything")
    answer_memory.delete(row.id)
    assert answer_book.learned_type("Will you relocate to Austin?", options) is None


def test_a_reworded_classifier_prompt_learns_types_afresh(monkeypatch):
    from resume_tailor.apply.answers import answer

    answer_book.learn_type("Will you relocate?", ["Yes", "No"], "willing_to_relocate", "x")
    monkeypatch.setattr(answer, "_CLASSIFY_PROMPT_VERSION", answer._CLASSIFY_PROMPT_VERSION + 1)
    assert answer_book.learned_type("Will you relocate?", ["Yes", "No"]) is None
    [row] = answer_memory.list_answers()  # still listed, and forgettable
    answer_memory.delete(row.id)
    assert answer_memory.list_answers() == []


def test_classify_questions_reads_learned_types_without_a_model(monkeypatch):
    from resume_tailor.apply.answers import answer, questions

    answer_book.learn_type("Will you relocate?", ["Yes", "No"], "willing_to_relocate", "x")

    def no_model(*_a, **_k):
        raise AssertionError("the model was asked")

    monkeypatch.setattr(answer.llm, "client_for", no_model)
    question = questions.Question("Will you relocate?", kind="choice", options=("Yes", "No"))
    assert answer.classify_questions([question]) == ["willing_to_relocate"]
