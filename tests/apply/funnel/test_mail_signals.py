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


def test_a_footer_link_to_linkedin_is_not_linkedin_writing():
    rows = [_app("li", "LinkedIn", role="Software Engineer Intern")]
    other = _mail("Cadence <no-reply@us.greenhouse-mail.io>", "Your Cadence Application",
                  "We have decided to move forward with other candidates for the Software "
                  "Engineer Intern position. Follow us on LinkedIn.")
    assert mail_signals.match(other, rows).app_id is None
    own = _mail("LinkedIn <careers@linkedin.com>", "Your application to LinkedIn")
    assert mail_signals.match(own, rows).app_id == "li"


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


@pytest.mark.parametrize(
    ("subject", "body", "expected"),
    [
        # A phrase wrapped onto a new line, or typed with a curly apostrophe or NBSP.
        ("Update", "After review we have decided to move forward with other\ncandidates.",
         "rejected"),
        ("Update", "We won’t be moving forward with your application.", "rejected"),
        ("Update", "We​ regret to inform you that the role is closed.", "rejected"),
        # Wordings the first list missed.
        ("Your application", "The team decided to move forward with another candidate.",
         "rejected"),
        ("Your application", "We have decided to move forward with candidates whose "
         "background fits more closely.", "rejected"),
        ("Hello", "We are no longer hiring for this position.", "rejected"),
        ("Hello", "While impressed, we have not selected your application this time.",
         "rejected"),
        ("Hello", "We have decided to progress with other candidates.", "rejected"),
        ("Hello", "We made the difficult decision to not move forward.", "rejected"),
        ("Hello", "We will not be able to move forward with your candidacy.", "rejected"),
        ("Hello", "We decided to offer the position to another candidate.", "rejected"),
        ("Hello", "We are sorry, but you do not meet the minimum qualifications.", "rejected"),
        ("Hello", "Your assessment expired, so your application is no longer active.",
         "rejected"),
        # A cancelled interview: the role was filled, so it is a rejection.
        ("RE: Phone screen interview invitation", "Sorry, we have to cancel. The role you "
         "were going to interview for has been filled.", "rejected"),
        # An offer made to someone else is not an offer.
        ("Update", "We are extending an offer to another candidate.", "rejected"),
        # A rejection with a newsletter footer is still a rejection; an alert is not news.
        ("Update", "We regret to inform you. Join our newsletter for updates.", "rejected"),
        ("Jobs picked for you", "We'd like to speak with you about these jobs.", None),
    ],
)
def test_classify_reads_wrapped_text_and_more_wordings(subject, body, expected):
    assert mail_signals.classify(subject, body) == expected


@pytest.mark.parametrize(
    "body",
    [
        "Thank you for applying! We'll let you know if you are selected for the next step "
        "or if you are no longer being considered for the role.",
        "Thanks for applying. If you are not selected, keep an eye on our jobs page.",
        "Thank you for applying. If you haven't heard from us within four weeks, we've "
        "likely moved forward with other candidates.",
        "Thank you for applying. If your experience is a fit, we'll reach out to schedule "
        "an interview.",
        "Thank you for your application. Since the role needs coding, you may receive an "
        "invitation to take a coding assessment.",
    ],
)
def test_a_conditional_next_step_is_only_an_acknowledgement(body):
    assert mail_signals.classify("Thank you for applying", body) == "sent"


def test_normalize_folds_spacing_quotes_and_invisible_characters():
    assert mail_signals.normalize("We’re  not\n\nmoving​ forward") == (
        "We're not moving forward"
    )


def test_check_flags_an_email_older_than_the_application():
    sent = store_models.StatusChange(status="submitted", at="2026-10-10T18:00:00+00:00")
    app = _app("a", "Acme", status_history=[sent])
    assert mail_signals.check("rejected", app, "2026-09-01") == (
        "This email is older than the application."
    )
    # A day of slack for time zones.
    assert mail_signals.check("rejected", app, "2026-10-09") == ""
