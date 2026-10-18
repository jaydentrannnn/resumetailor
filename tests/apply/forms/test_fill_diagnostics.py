"""`fill_diagnostics`: how a fill ended, in stable categories, with no values."""

from __future__ import annotations

from resume_tailor.apply.forms import fill_diagnostics, fill_outcomes
from resume_tailor.apply.funnel.store_models import FillResult


def _category(**fields) -> str:
    needs_review = fields.pop("needs_review", None)
    return fill_diagnostics.end_category(FillResult(**fields), needs_review)


def test_end_categories():
    assert _category(status="submitted") == "submitted"
    assert _category(status="awaiting_otp", handoff_reason="Enter the code") == "handoff_code"
    assert _category(status="awaiting_review", handoff_reason=fill_outcomes.NO_FORM_MSG) == "no_form"
    assert _category(status="awaiting_review",
                     handoff_reason="Sign in to the site in the opened tab") == "handoff_sign_in"
    assert _category(status="awaiting_review",
                     handoff_reason="Create your Oracle account in the opened tab") == "handoff_account"
    assert _category(status="fill_failed",
                     handoff_reason="The posting is closed or no longer available") == "closed"
    assert _category(status="fill_failed", handoff_reason="fill stopped responding") == "stalled"
    assert _category(status="awaiting_review",
                     needs_review=["Application fill reached its time limit"]) == "time_limit"
    assert _category(status="awaiting_review", ready_to_submit=True) == "ready"
    assert _category(status="awaiting_review", required_empty=["Email"]) == "review_missing"


def test_build_has_platforms_counts_and_no_values():
    result = FillResult(status="awaiting_review", filled=[{"label": "Email", "value": "a@b.example"}])
    built = fill_diagnostics.build(
        result, posting_url="https://jobs.lever.co/acme/1", landed_url="https://acme.icims.com/jobs/2/job",
        elapsed_s=12.34, model_calls=3,
    )
    assert built["platform"] == {"posting": "lever", "landed": "icims"}
    assert built["elapsed_s"] == 12.3 and built["model_calls"] == 3
    assert built["app_version"]
    assert "a@b.example" not in str(built)
