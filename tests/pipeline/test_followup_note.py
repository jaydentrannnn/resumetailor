"""Follow-up and thank-you notes (`followup_note`): the claim check and its fallback."""

from __future__ import annotations

import pytest

from resume_tailor import config
from resume_tailor.pipeline import followup_note
from resume_tailor.pipeline.followup_note import FollowupLLM
from tests.fixtures import synthetic_resume

SENT = {"proj_b1": "Indexed research notes with embeddings."}


class _Reply:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _Client:
    def __init__(self, queue, calls):
        self.messages = self
        self._queue, self._calls = queue, calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return _Reply(self._queue.pop(0))


@pytest.fixture
def note_calls(monkeypatch):
    calls: list[dict] = []
    queue: list = []
    monkeypatch.setattr(followup_note.llm, "client_for", lambda purpose: _Client(queue, calls))
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "test-key")

    def enqueue(*replies):
        queue.extend(replies)
        return calls

    return enqueue


def _draft(kind="follow_up", channel="email", **extra):
    kwargs = dict(resume=synthetic_resume(), role="Data Analyst", company="Acme Health",
                  bullets=SENT, sent_on="2026-10-01", recipient="Priya",
                  notes=["2026-10-12 interview completed: we talked about the claims pipeline"])
    return followup_note.draft(kind, channel, **{**kwargs, **extra})


def test_a_claim_free_draft_is_kept_with_its_subject(note_calls):
    calls = note_calls(FollowupLLM(
        subject="Following up on my Data Analyst application",
        body="Hi Priya, I applied to Acme Health on 2026-10-01 and remain very interested. "
             "Indexing research notes with embeddings taught me a lot. Best regards",
    ))
    note = _draft()
    assert (note.source, note.subject, note.warnings) == (
        "llm", "Following up on my Data Analyst application", [])
    user = calls[0]["messages"][0]["content"]
    assert "<recipient>Priya</recipient>" in user and "claims pipeline" in user
    assert calls[0]["model"] == config.model_for("followup")


def test_a_thank_you_may_echo_the_candidates_own_interview_notes(note_calls):
    # The candidate's name, a weekday and a salutation claim nothing.
    note_calls(FollowupLLM(body="Dear Hiring Team, thank you for walking me through the "
                                "claims pipeline on Monday. Best regards, Jordan Rivera"))
    note = _draft(kind="thank_you", channel="linkedin")
    assert note.source == "llm" and note.subject == ""


def test_an_invented_claim_falls_back_to_the_plain_template(note_calls):
    note_calls(FollowupLLM(subject="Hi", body="I have 5 years of Kubernetes experience."))
    note = _draft(channel="portal")
    assert note.source == "template" and note.subject == ""
    assert "Kubernetes" in note.warnings[0] and "5" in note.warnings[0]
    assert note.body.startswith("Hi Priya,")
    assert "the Data Analyst position at Acme Health on 2026-10-01" in note.body


def test_an_empty_draft_falls_back_too(note_calls):
    note_calls(FollowupLLM(body=" "))
    note = _draft(kind="thank_you", recipient="")
    assert note.source == "template" and note.subject == "Thank you: Data Analyst"
    assert note.body.startswith("Hello,") and "empty note" in note.warnings[0]


def test_sent_facts_survive_removal_from_the_master_with_a_warning(note_calls):
    resume = synthetic_resume()
    resume.projects[0].bullets.clear()
    note_calls(FollowupLLM(body="I indexed 1,200 research notes with embeddings."))
    note = _draft(resume=resume, bullets={
        "proj_b1": "Indexed 1,200 research notes with embeddings.",
    })
    assert note.source == "llm"
    assert any("no longer" in w and "master resume" in w for w in note.warnings)


def test_current_master_skills_and_tags_do_not_support_follow_up_claims(note_calls):
    resume = synthetic_resume()
    resume.skills[0].items.append("Kubernetes")
    resume.projects[0].bullets[0].tags.append("Kubernetes")
    note_calls(FollowupLLM(body="I indexed notes with Kubernetes."))
    note = _draft(resume=resume)
    assert note.source == "template"
    assert "Kubernetes" in note.warnings[0]


def test_posting_numbers_cannot_support_candidate_claims(note_calls):
    note_calls(FollowupLLM(body="I indexed 5 research notes."))
    note = _draft(jd_text="The role requires 5 years of experience.")
    assert note.source == "template"
    assert "5" in note.warnings[0]
