"""Per-ATS CSS selector hints for the deterministic form filler.

Maps known selectors to canonical field keys from ``packet.build_fields``. Special keys
``submit``, ``confirmation_text``, and ``resume_upload`` are reserved for the fill runner.
Label-driven ATSs (Ashby, Workday) rely on ``SYNONYMS`` when hints are sparse.
"""

from __future__ import annotations

import re

#: Every flat key ``build_fields`` may emit (plan section 3.4).
CANONICAL_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "first_name",
        "middle_name",
        "last_name",
        "full_name",
        "preferred_name",
        "has_preferred_name",
        "email",
        "phone",
        "phone_device_type",
        "phone_country_code",
        "phone_country_region",
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "website",
        "work_authorization",
        "authorized_to_work",
        "authorization_country",
        "requires_sponsorship",
        "requires_sponsorship_future",
        "requires_sponsorship_any",
        "f1_opt_eligible",
        "earliest_start",
        "notice_period",
        "education_start_month",
        "graduation_month",
        "degree_level",
        "major",
        "school",
        "gpa",
        "salary_expectation",
        "salary_expectation_number",
        "salary_hourly",
        "salary_hourly_number",
        "salary_yearly",
        "salary_yearly_number",
        "willing_to_relocate",
        "how_heard",
        "gender",
        "race",
        "race_detail",
        "hispanic_latino",
        "veteran_status",
        "disability_status",
        "current_company",
        "current_title",
    }
)

#: Reserved hint values — not canonical field keys but used by the fill runner.
_SPECIAL_HINT_KEYS: frozenset[str] = frozenset(
    {"submit", "confirmation_text", "resume_upload"}
)

#: Ordered (regex, canonical_key) pairs for label matching in ``filler.js``.
#: F-1/OPT/CPT must win before the generic sponsorship rule (plan section 3.2).
SYNONYMS: list[tuple[str, str]] = [
    (r"f-1|opt|cpt", "f1_opt_eligible"),
    (r"current(?:ly)?\s*(?:or|and|/)\s*future.*sponsor|now\s*or\s*in\s*the\s*future.*sponsor", "requires_sponsorship_any"),
    (r"phone\s*(?:device\s*)?type", "phone_device_type"),
    (r"notice\s*period|weeks\s*of\s*notice", "notice_period"),
    (r"(?:legally\s*)?authorized\s*to\s*work|right\s*to\s*work", "authorized_to_work"),
    (r"country\s*(?:/|or)?\s*(?:dial(?:ling|ing)?\s*)?code|dial(?:ling|ing)?\s*code|calling\s*code|tel-country-code", "phone_country_code"),
    # "Phone Extension" is its own (optional) field; no profile fact feeds it.
    (r"\bextension\b|\bext\.?$", "phone_extension"),
    (r"phone|mobile|telephone|cell", "phone"),
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"portfolio|personal site|personal website", "portfolio_url"),
    (r"authorized to work|work authorization|legally authorized", "work_authorization"),
    (r"sponsorship", "requires_sponsorship"),
    (r"when can you start|start date|available to start|availability", "earliest_start"),
    (r"graduation|expected graduation", "graduation_month"),
    (r"how did you hear", "how_heard"),
    (r"gender", "gender"),
    (r"hispanic|latino", "hispanic_latino"),
    (r"race|ethnicity", "race"),
    (r"veteran", "veteran_status"),
    (r"disability", "disability_status"),
    (r"salary|compensation|pay expectation|desired pay|pay rate|\bwage", "salary_expectation"),
    (r"relocat", "willing_to_relocate"),
    (r"current company|employer", "current_company"),
    (r"current title|job title", "current_title"),
    (r"pronouns", "pronouns"),
    # The "I have a preferred name" checkbox that reveals the preferred-name inputs.
    (r"(?:i )?have a preferred name|use (?:a )?preferred name", "has_preferred_name"),
    (r"preferred first name|preferred name", "preferred_name"),
    (r"first name|given name", "first_name"),
    (r"middle name", "middle_name"),
    (r"last name|family name|surname", "last_name"),
    (r"preferred name", "preferred_name"),
    (r"email", "email"),
    (r"address line 1|street address", "address_line1"),
    (r"address line 2|apt|suite", "address_line2"),
    (r"city", "city"),
    (r"state|province", "state"),
    (r"zip|postal", "postal_code"),
    (r"country", "country"),
    (r"website|url", "website"),
    (r"degree", "degree_level"),
    (r"major|field of study", "major"),
    (r"school|university|college", "school"),
    (r"gpa", "gpa"),
]

ATS_HINTS: dict[str, dict[str, str]] = {
    "greenhouse": {
        "#first_name": "first_name",
        "#last_name": "last_name",
        "#email": "email",
        "#phone": "phone",
        "#job_application_location": "city",
        "#candidate-location": "city",
        "#school--0": "school",
        "#degree--0": "degree_level",
        "#discipline--0": "major",
        "input[name='job_application[resume]']": "resume_upload",
        "input[type='file']#resume": "resume_upload",
        "#resume": "resume_upload",
        "#submit_app": "submit",
        "button#submit_app": "submit",
        "input[type='submit'][value='Submit application']": "submit",
        "button[type='submit']": "submit",
        "confirmation_text": "Thank you for applying",
    },
    "lever": {
        "input[name='name']": "full_name",
        "input[name='email']": "email",
        "input[name='phone']": "phone",
        "input[name='org']": "current_company",
        "input[name='urls[LinkedIn]']": "linkedin_url",
        "input[name='urls[GitHub]']": "github_url",
        "input[name='resume']": "resume_upload",
        "button.postings-btn.template-btn-submit": "submit",
        "confirmation_text": "Application submitted",
    },
    "ashby": {
        "input[type='file']": "resume_upload",
        "button[type='submit']": "submit",
        "confirmation_text": "Thank you",
    },
    # Current Workday apply flow (captured 2026-09): inputs carry `<section>--<field>` ids.
    "workday": {
        "input[id='name--legalName--firstName']": "first_name",
        "input[id='name--legalName--middleName']": "middle_name",
        "input[id='name--legalName--lastName']": "last_name",
        "input[id='name--preferredName--firstName']": "preferred_name",
        "input[id='name--preferredName--lastName']": "last_name",
        "input[id='address--addressLine1']": "address_line1",
        "input[id='address--addressLine2']": "address_line2",
        "input[id='address--city']": "city",
        "input[id='address--postalCode']": "postal_code",
        "input[id='phoneNumber--phoneNumber']": "phone",
        "input[data-automation-id='file-upload-input-ref']": "resume_upload",
        "confirmation_text": "Thank you",
    },
    "oracle": {
        "confirmation_text": "Thank you for applying",
    },
}

#: Button labels or selectors to click before the form is visible (plan section 8.2).
ATS_PRE_FILL_CLICKS: dict[str, list[str]] = {
    "greenhouse": ["#apply_button", "text=Apply", "text=Apply Now"],
    "lever": ["text=Apply for this job", "text=Apply", "text=Apply Now"],
    "ashby": ["text=Apply", "text=Apply Now"],
    "workday": [
        "text=Apply Manually",
        "a[data-automation-id='applyManually']",
        "button[data-automation-id='applyManually']",
        "text=Apply",
        "text=Apply Now",
        "a[data-automation-id='applyButton']",
        "button[data-automation-id='applyButton']",
    ],
    "oracle": [
        "button[data-test-id='apply-button']",
        "a[data-test-id='apply-button']",
        "text=Apply Now",
        "text=Apply",
    ],
}


def hints_for(ats: str) -> dict[str, str]:
    """Return selector hints for ``ats``, or an empty dict when unknown."""
    return dict(ATS_HINTS.get(ats.lower(), {}))


def is_valid_hint_entry(selector: str, value: str) -> bool:
    """True when one ATS hint row uses a known selector/value pairing."""
    if selector == "confirmation_text":
        return bool(value.strip())
    return value in CANONICAL_FIELD_KEYS or value in {"submit", "resume_upload"}


def looks_like_css_selector(selector: str) -> bool:
    """Cheap sanity check that a hint key resembles a CSS selector."""
    if selector in _SPECIAL_HINT_KEYS:
        return True
    return bool(re.search(r"[#.\[\w]", selector))
