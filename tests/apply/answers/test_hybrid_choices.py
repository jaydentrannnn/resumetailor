"""The model's cached dropdown picks: listed for the Profile page, forgettable."""

import json

import pytest

from resume_tailor import config
from resume_tailor.apply.answers import hybrid_resolver
from resume_tailor.apply.answers import profile as profile_mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(config, "APPLICANT_PROFILE_PATH", tmp_path / "applicant_profile.json")
    profile_mod.save_profile(profile_mod.ApplicantProfile(first_name="Ada"))


def _write(entries):
    hybrid_resolver._write_choices(entries)


def test_only_picks_for_the_current_profile_are_listed():
    digest = hybrid_resolver.current_digest()
    _write({
        "k1": {"action": "select_combobox", "value": "Yes", "label": "Remote ok?", "digest": digest,
               "version": hybrid_resolver._RESOLVER_PROMPT_VERSION},
        "k2": {"action": "select_combobox", "value": "No", "label": "Old", "digest": "stale"},
        "k3": {"action": "select_combobox", "value": "Yes", "label": "Legacy entry"},
    })
    assert hybrid_resolver.list_choices() == [{"key": "k1", "label": "Remote ok?", "answer": "Yes"}]


def test_forget_removes_one_pick():
    digest = hybrid_resolver.current_digest()
    _write({"k1": {"action": "choose_radio", "value": "Yes", "label": "Q", "digest": digest}})
    assert hybrid_resolver.forget_choice("k1")
    assert not hybrid_resolver.forget_choice("k1")
    assert hybrid_resolver.list_choices() == []
    assert json.loads(hybrid_resolver._choices_path().read_text(encoding="utf-8")) == {}
