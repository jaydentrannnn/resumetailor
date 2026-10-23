"""Job emails read for what happened and which application they are about (`mail_signals`)."""

from __future__ import annotations

import pytest

from resume_tailor.apply.funnel import mail_signals, store_models


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        ("Your application to Acme", "Thank you for your interest. Unfortunately, we will not be "
         "moving forward with your application at this time.", "rejected"),
        ("Interview invitation - Data Analyst Intern", "Hi Sam, we'd like to invite you to a "
         "video interview. Please share your availability for next week.", "interview_invited"),
        ("Next steps: Globex", "Please complete the HackerRank assessment within 5 days.",
         "assessment"),
        ("Offer letter", "We are pleased to extend an offer for the Summer Analyst role.", "offer"),
        ("We received your application", "Thanks for applying to Initech! Our team will review "
         "it.", "sent"),
        # A rejection that mentions the assessment is still a rejection.
        ("Update", "Thank you for completing the online assessment. Unfortunately we have "
         "decided not to proceed with your application.", "rejected"),
        ("Jobs picked for you", "New jobs for you: Data Analyst at Acme. We are pleased to "
         "extend an offer of free webinars.", None),
        ("Lunch on Friday?", "Want to grab lunch?", None),
    ],
)
def test_classify_reads_the_subject_and_opening(subject, body, expected):
    assert mail_signals.classify(subject, body) == expected


def test_a_signal_past_the_opening_is_not_read():
    body = "Hello! " + "Weekly update. " * 80 + "We regret to inform you."
    assert mail_signals.classify("Update", body) is None


def _app(key, company, role="Data Analyst Intern", status="submitted", **extra):
    return store_models.Application(
        source="t", source_job_id=key, company=company, role=role, status=status, **extra
    )


def _mail(sender, subject, body=""):
    return mail_signals.Mail("m1", sender, subject, body, "2026-10-20")


def test_a_named_company_matches_its_one_application():
    rows = [_app("a", "Acme Analytics, Inc."), _app("b", "Globex")]
    found = mail_signals.match(_mail("Acme Recruiting <no-reply@us.greenhouse-mail.io>",
                                     "Your application to Acme Analytics"), rows)
    assert found.app_id == "a" and "company named" in found.reason


def test_two_roles_at_one_company_tie_unless_the_role_is_named():
    rows = [_app("a", "Acme", role="Data Analyst Intern"),
            _app("b", "Acme", role="Software Engineer Intern")]
    tie = mail_signals.match(_mail("jobs@acme.com", "Your application to Acme"), rows)
    assert tie.app_id is None and sorted(tie.candidates) == ["a", "b"]
    named = mail_signals.match(
        _mail("jobs@acme.com", "Software Engineer Intern at Acme: next steps"), rows)
    assert named.app_id == "b"


def test_a_requisition_id_picks_the_row():
    rows = [_app("a", "Big Bank", canonical_key="workday:bigbank:R5054820", ats="workday"),
            _app("b", "Big Bank", canonical_key="workday:bigbank:R1111111", ats="workday")]
    found = mail_signals.match(_mail("bigbank@myworkday.com", "Application R5054820 received"),
                               rows)
    assert found.app_id == "a"


def test_an_ats_sender_alone_or_an_unrelated_row_never_matches():
    rows = [_app("a", "Acme"), _app("found", "Globex", status="discovered")]
    assert mail_signals.match(_mail("no-reply@greenhouse-mail.io", "Thanks for applying"),
                              rows).app_id is None
    assert mail_signals.match(_mail("jobs@globex.com", "Globex interview"), rows).app_id is None


def test_check_flags_a_proposal_that_contradicts_the_record():
    offer = store_models.OutcomeEvent(id="o", type="offer", occurred_on="2026-10-01",
                                      recorded_at="2026-10-01T00:00:00+00:00")
    app = _app("a", "Acme", outcome_events=[offer])
    assert "offer" in mail_signals.check("rejected", app, "2026-10-20")
    assert "Already recorded" in mail_signals.check("offer", app, "2026-10-01")
    assert mail_signals.check("sent", app, None) == "Already marked as sent."
    unsure = _app("u", "Acme", status="submit_unconfirmed")
    assert mail_signals.check("sent", unsure, None) == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2026-10-20", "2026-10-20"), ("Tue, 20 Oct 2026 09:15:00 -0700", "2026-10-20"),
     ("2026-10-20T09:15:00Z", "2026-10-20"), ("yesterday", None), ("", None)],
)
def test_received_on_reads_iso_and_mail_dates(raw, expected):
    assert mail_signals.received_on(raw) == expected
