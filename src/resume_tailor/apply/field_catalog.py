"""Conservative field classification and manual-review policy for Apply."""

from __future__ import annotations

import re
from typing import Literal

from resume_tailor.apply.field_matcher import normalize
from resume_tailor.apply.field_types import FieldObservation

Classification = Literal["known", "manual_review", "unknown"]


def classify(field: FieldObservation) -> tuple[Classification, str]:
    """Classify from explicit semantics before ambiguous nearby words."""
    label = normalize(field.label)
    section = normalize(field.section_id)
    attrs = field.constraints
    auto = normalize(str(attrs.get("autocomplete") or ""))
    name = normalize(str(attrs.get("name") or ""))
    input_type = normalize(str(attrs.get("input_type") or ""))
    if input_type == "password" or auto in {"current password", "new password", "one time code"} or re.search(r"\b(password|passcode|verification code|one time code)\b", label):
        return "manual_review", "credential_or_verification"
    if re.search(r"\b(salary|compensation|pay expectation|desired pay|pay rate|wages?)\b", label):
        # Deterministic per-posting answer (`apply/salary.py`), in the unit asked for.
        unit = "salary_hourly" if "hour" in label else "salary_yearly" if re.search(r"\b(year|annual)", label) else "salary_expectation"
        return "known", f"{unit}_number" if input_type == "number" else unit
    if re.search(r"\b(agree|agreement|certif\w*|attest\w*|signature|arbitration|terms of service)\b", label):
        return "manual_review", "agreement_or_signature"
    if field.canonical_key:
        return "known", field.canonical_key
    if auto == "tel country code" or re.search(r"\b(calling|dialing|dialling) code\b", label):
        return "known", "phone_country_code"
    if "country" in label and field.control_kind in {"combobox", "native_select"}:
        if "phone" in section and bool(attrs.get("phone_sibling")):
            return "known", "phone_country_code"
        return "known", "country"
    if field.control_kind == "checkbox" and "have a preferred name" in label:
        return "known", "has_preferred_name"
    if "preferred first name" in label or "preferred name" in label:
        return "known", "preferred_name"
    if "first name" in label or auto == "given name":
        return "known", "first_name"
    if "middle name" in label:
        return "known", "middle_name"
    if "last name" in label or "family name" in label:
        return "known", "last_name"
    if "hispanic" in label or "latino" in label:
        return "known", "hispanic_latino"
    if "race" in label or "ethnicity" in label:
        return "known", "race"
    if "future" in label and "sponsor" in label and "now" in label:
        return "known", "requires_sponsorship_any"
    if "future" in label and "sponsor" in label:
        return "known", "requires_sponsorship_future"
    if "sponsor" in label:
        return "known", "requires_sponsorship"
    if "notice period" in label or "weeks of notice" in label:
        return "known", "notice_period"
    if "start" in label and re.search(r"education|school|experience|employment|work history", section):
        return "unknown", ""
    if "when can you start" in label or "available to start" in label:
        return "known", "earliest_start"
    if "start date" in label and not section:
        return "unknown", ""
    if "email" in label or auto == "email":
        return "known", "email"
    if "linkedin" in label:
        return "known", "linkedin_url"
    if "github" in label:
        return "known", "github_url"
    if "portfolio" in label or "personal website" in label:
        return "known", "portfolio_url"
    if "phone" in label or auto == "tel":
        return "known", "phone"
    if "address line 2" in label or "address 2" in label or auto == "address line2":
        return "known", "address_line2"
    if "address" in label or auto == "street address":
        return "known", "address_line1"
    if "postal" in label or "zip code" in label:
        return "known", "postal_code"
    if "state" in label or "province" in label:
        return "known", "state"
    if "city" in label:
        return "known", "city"
    if "school" in label:
        return "known", "school"
    if "degree" in label:
        return "known", "degree_level"
    if "discipline" in label or "major" in label or "field of study" in label:
        return "known", "major"
    if "gpa" in label:
        return "known", "gpa"
    if "graduation" in label and "year" in label:
        return "known", "graduation_month"
    if "legally authorized" in label or "authorized to work" in label:
        return "known", "authorized_to_work"
    return "unknown", ""


def may_generate_written_answer(field: FieldObservation) -> bool:
    """Limit prose generation to clear professional, job-related questions."""
    if field.control_kind not in {"textarea", "text"}:
        return False
    label = normalize(field.label)
    if re.search(
        r"\b(salary|compensation|pay|wage|citizen|visa|sponsor|authorization|"
        r"race|ethnic|hispanic|latino|gender|disabil\w*|veteran|agreement|"
        r"certif\w*|attest\w*|signature|password|ssn|social security)\b",
        label,
    ):
        return False
    return bool(re.search(
        r"\b(why|describe|explain|tell us|what interests|experience with|"
        r"motivation|qualification|strengths|skills relevant)\b",
        label,
    ))
