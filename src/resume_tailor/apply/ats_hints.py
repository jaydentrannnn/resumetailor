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
        "how_heard_detail",
        "gender",
        "race",
        "race_detail",
        "hispanic_latino",
        "veteran_status",
        "disability_status",
        "current_company",
        "current_title",
        "languages",
        "over_18",
        "visa_status",
        "class_year",
        "school_email",
        "security_clearance",
        "drivers_license",
        "hours_per_week",
    }
)

#: Reserved hint values — not canonical field keys but used by the fill runner.
_SPECIAL_HINT_KEYS: frozenset[str] = frozenset(
    {"submit", "confirmation_text", "resume_upload"}
)

#: "Authorized / permitted / eligible to work", and "can you provide proof of
#: eligibility" (Workday reveals it after a Yes): proving eligibility follows from being
#: authorised, so both read the same profile fact. Proof of a degree, a licence or
#: veteran status is not work authorization. Also used by ``field_catalog.classify``.
AUTHORIZED_TO_WORK = (
    r"^(?![\s\S]*(?:veteran|degree|enrol|vaccin|licen[sc]e|clearance))"
    r"[\s\S]*(?:(?:authori[sz]ed|permitted|eligible|allowed)\s*to\s*(?:legally\s*)?work"
    r"|right\s*to\s*work|(?:employment|work)\s*eligibility"
    r"|(?:proof|evidence|documentation|documents?)\s*(?:of|for|showing|verifying)\s*"
    r"(?:your\s*)?(?:employment\s*|work\s*)?(?:eligibility|authori[sz]ation|right\s*to\s*work"
    r"|identity\s*and\s*(?:employment\s*)?eligibility))"
)

#: "Are you over the age of 18?" and its variants; never "under 18", whose Yes/No is
#: the inverse of the profile answer.
OVER_18 = (
    r"^(?![\s\S]*\bunder\b)[\s\S]*(?:\b(?:over|at\s*least|older\s*than)\s*(?:the\s*age\s*of\s*)?18\b"
    r"|\b18\s*(?:years?|yrs?)\s*(?:of\s*age|old|or\s*older)|\bage\s*of\s*(?:18|majority)\b"
    r"|legal\s*(?:working\s*)?age)"
)

#: Ordered (regex, canonical_key) pairs for label matching in ``filler.js``.
#: F-1/OPT/CPT must win before the generic sponsorship rule (plan section 3.2).
SYNONYMS: list[tuple[str, str]] = [
    # "What is your current visa status (F-1, H-1B, ...)?" names F-1 too: before the OPT rule.
    (r"visa\s*(?:status|type)|immigration\s*status|current\s*visa", "visa_status"),
    # Whole words: "opt" inside "optionID" / "optional" is not OPT.
    (r"\bf-?1\b|\bopt\b|\bcpt\b", "f1_opt_eligible"),
    (r"current(?:ly)?\s*(?:or|and|/)\s*future.*sponsor|now,?\s*or\s*(?:will\s*you\s*)?in\s*the\s*future.*sponsor", "requires_sponsorship_any"),
    # A free-text "What languages do you speak?"; not Workday's per-row "Language"
    # dropdown (`workday_repeaters`) and never programming languages.
    (r"^(?!.*programming).*(?:languages?\b.{0,30}\b(?:speak|spoken|fluent)|\bspoken languages?\b|\bspeak\b.{0,30}\blanguages\b)", "languages"),
    (r"phone\s*(?:device\s*)?type", "phone_device_type"),
    (r"notice\s*period|weeks\s*of\s*notice", "notice_period"),
    (AUTHORIZED_TO_WORK, "authorized_to_work"),
    (OVER_18, "over_18"),
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
    # "If other, how did you hear about us? Please specify" is the free-text follow-up.
    (r"(?:hear|source|referr).{0,40}specify|specify.{0,40}(?:hear|source|referr)", "how_heard_detail"),
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
    # Before the generic email rule: "University email" wants the school address.
    (r"(?:school|university|college|student|\.edu)\s*e-?mail", "school_email"),
    (r"email", "email"),
    (r"address line 1|street address", "address_line1"),
    (r"address line 2|apt|suite", "address_line2"),
    # Whole words: "capacity" is not a city, "statement" is not a state.
    (r"\bcity\b", "city"),
    (r"\bstate\b|province", "state"),
    (r"zip|postal", "postal_code"),
    (r"country", "country"),
    (r"website|url", "website"),
    (r"degree", "degree_level"),
    (r"major|field of study|discipline", "major"),
    (r"school|university|college", "school"),
    (r"gpa", "gpa"),
    # "Class year" alone often means the graduation year, so it is not matched here.
    (
        r"class\s*standing|academic\s*(?:standing|level)|year\s*in\s*school"
        r"|(?:current\s*)?year\s*of\s*study|student\s*classification",
        "class_year",
    ),
    (r"security\s*clearance|clearance\s*level", "security_clearance"),
    (r"driver'?s?\s*licen[sc]e", "drivers_license"),
    (r"hours\s*(?:per|a|each)\s*week|weekly\s*hours", "hours_per_week"),
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
        "input[name='urls[Portfolio]']": "portfolio_url",
        "input[name='urls[Other]']": "website",
        "input[name='resume']": "resume_upload",
        "button.postings-btn.template-btn-submit": "submit",
        "confirmation_text": "Application submitted",
    },
    # Ashby's built-in questions carry `_systemfield_<name>` ids; custom ones are
    # matched by label.
    "ashby": {
        "input[id='_systemfield_name']": "full_name",
        "input[id='_systemfield_email']": "email",
        "input[id='_systemfield_resume']": "resume_upload",
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
    # Wizard platforms (`wizards.py` names their screens); fields are matched by label.
    "icims": {"confirmation_text": "Thank you"},
    "taleo": {"confirmation_text": "Thank you for submitting"},
    "successfactors": {"confirmation_text": "Thank you"},
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
