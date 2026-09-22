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
        "last_name",
        "full_name",
        "preferred_name",
        "email",
        "phone",
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
        "requires_sponsorship",
        "requires_sponsorship_future",
        "f1_opt_eligible",
        "earliest_start",
        "graduation_month",
        "degree_level",
        "major",
        "school",
        "gpa",
        "salary_expectation",
        "willing_to_relocate",
        "how_heard",
        "gender",
        "race",
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
    (r"phone|mobile|telephone|cell", "phone"),
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"portfolio|personal site|personal website", "portfolio_url"),
    (r"authorized to work|work authorization|legally authorized", "work_authorization"),
    (r"sponsorship", "requires_sponsorship"),
    (r"start date|available to start|availability", "earliest_start"),
    (r"graduation|expected graduation", "graduation_month"),
    (r"how did you hear", "how_heard"),
    (r"gender", "gender"),
    (r"race|ethnicity", "race"),
    (r"veteran", "veteran_status"),
    (r"disability", "disability_status"),
    (r"salary|compensation", "salary_expectation"),
    (r"relocat", "willing_to_relocate"),
    (r"current company|employer", "current_company"),
    (r"current title|job title", "current_title"),
    (r"pronouns", "pronouns"),
    (r"first name|given name", "first_name"),
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
        "input[name='job_application[resume]']": "resume_upload",
        "#submit_app": "submit",
        "input[type='submit'][value='Submit application']": "submit",
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
}

#: Button labels or selectors to click before the form is visible (plan section 8.2).
ATS_PRE_FILL_CLICKS: dict[str, list[str]] = {
    "greenhouse": ["Apply", "#apply_button"],
    "lever": ["Apply for this job", "Apply"],
    "ashby": ["Apply"],
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
