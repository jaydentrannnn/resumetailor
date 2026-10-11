"""The «token» vocabulary of the Edit-layout-in-Word skeleton (`template_skeleton.py`).

One token per (section kind, field), each name unique so a token alone says what it is —
«Job dates» and «School dates» never need their surroundings to be told apart. A token
has three faces: the `sentinel` the skeleton's sentinel resume renders (letters only, so
rendering never splits or reformats it), the `label` the person sees as «label», and the
`sample` it becomes when the edited file is read back (`skeleton_parse.py`), so the
analyzer sees an ordinary resume again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: «Label» or <<Label>> (« is hard to type on most keyboards). Never spans a tab.
TOKEN_RE = re.compile(r"«\s*([^«»\t]+?)\s*»|<<\s*([^<>\t]+?)\s*>>")
#: «custom: Street address» adds (or keeps) an editable line.
CUSTOM_PREFIX = "custom:"


@dataclass(frozen=True)
class Token:
    kind: str  # "name", "contact", "experience", "education", "project", "skills", "list"
    field: str
    label: str
    sentinel: str
    sample: str


TOKENS: tuple[Token, ...] = (
    Token("name", "name", "Name", "QQNAMEQQ", "Jordan Rivera"),
    Token("contact", "location", "Location", "QQLOCATIONQQ", "Irvine, CA"),
    Token("contact", "email", "Email", "QQEMAILQQ", "jordan@example.com"),
    Token("contact", "phone", "Phone", "QQPHONEQQ", "(555) 123-4567"),
    # Profile links render as their label; only matched inside the contact block.
    Token("contact", "linkedin", "LinkedIn", "LinkedIn", "LinkedIn"),
    Token("contact", "github", "GitHub", "GitHub", "GitHub"),
    Token("education", "school", "School", "QQSCHOOLQQ", "University of California"),
    Token("education", "location", "School location", "QQEDULOCQQ", "Irvine, CA"),
    Token("education", "dates", "School dates", "QQEDUDATESQQ", "Sep 2019 - Jun 2023"),
    Token("education", "degree", "Degree", "QQDEGREEQQ", "Bachelor of Science in Economics"),
    Token(
        "education", "detail", "Education detail", "QQEDUDETAILQQ",
        "Relevant Coursework: Statistics, Econometrics",
    ),
    Token("experience", "company", "Company", "QQCOMPANYQQ", "Example Corporation"),
    Token("experience", "title", "Job title", "QQJOBTITLEQQ", "Business Analyst"),
    Token("experience", "location", "Job location", "QQJOBLOCQQ", "Los Angeles, CA"),
    # The range renders as "<start> – <end>"; `DATE_RANGE` spans it as one token.
    Token("experience", "dates", "Job dates", "QQJOBSTARTQQ", "Jan 2023 - Present"),
    Token(
        "experience", "bullet", "Job bullet", "QQJOBBULLETQQ",
        "Built a weekly reporting workflow that cut manual work for the team by 40 percent.",
    ),
    Token("project", "name", "Project", "QQPROJECTQQ", "Market Sizing Model"),
    Token("project", "tech", "Project tools", "QQTECHQQ", "Excel, Tableau"),
    Token("project", "link", "Project link", "QQLINKQQ", "Link"),
    Token("project", "date", "Project date", "QQPROJDATEQQ", "Mar 2024"),
    Token(
        "project", "bullet", "Project bullet", "QQPROJBULLETQQ",
        "Modelled regional demand from public data and presented the forecast to a panel.",
    ),
    Token("skills", "label", "Skill group", "QQSKILLLABELQQ", "Tools"),
    Token("skills", "body", "Skills", "QQSKILLSQQ", "Excel, SQL, Tableau"),
    Token("list", "item", "List item", "QQLISTITEMQQ", "Certified Business Analysis Professional"),
)

#: The experience date range: start sentinel through end sentinel, never across a tab.
DATE_RANGE = re.compile(r"QQJOBSTARTQQ[^\t]*?QQJOBENDQQ")
#: A custom line's sentinel carries its index into `TemplateProfile.custom_fields`.
CUSTOM_SENTINEL = re.compile(r"QQCUSTOM(\d+)QQ")

BY_LABEL: dict[str, Token] = {t.label.casefold(): t for t in TOKENS}
BY_SENTINEL: dict[str, Token] = {t.sentinel: t for t in TOKENS}
#: Tokens that open a new entry: their second appearance in a section starts entry two.
ENTRY_LEAD = {"experience": "company", "education": "school", "project": "name",
              "skills": "label", "list": "item"}  # fmt: skip
#: A section kind's analyzer override name (`template_analyze.analyze_docx(overrides=)`).
ANALYZER_KIND = {"experience": "experience", "education": "education",
                 "project": "projects", "skills": "skills", "list": "list"}  # fmt: skip


def label_text(label: str) -> str:
    """How a token reads in the document."""
    return f"«{label}»"


def lookup(text: str) -> Token | str | None:
    """The token named by a matched label: a `Token`, a custom line's label (`str`), or
    `None` for a name the app does not know."""
    name = " ".join(text.split())
    if name.casefold().startswith(CUSTOM_PREFIX):
        return name[len(CUSTOM_PREFIX):].strip() or None
    return BY_LABEL.get(name.casefold())
