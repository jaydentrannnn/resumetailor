"""Cover letter drafting for one tailoring run.

A seventh, opt-in LLM stage that runs after the fit loop succeeds. The model returns
body paragraphs plus posting-sourced fields (company, location, addressee); code assembles
the full business letter (date, salutation, closing, signature) and renders it through a
derived cover-letter template.

Hard facts never come from the model alone: company and addressee must appear verbatim in
the job posting; every resume claim is checked against the tailored bullets that actually
made the page. The fabrication guard is deliberately narrower than ``rewrite`` — ordinary
connective prose is allowed, but numbers, claim sentences, AI tells, and the word band
are enforced in code.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, events, llm, style
from .data import Bullet, MasterResume
from .jd import JobRequirements
from .rewrite import (
    _HAS_DIGIT,
    _TOKEN,
    _check_fabrication,
    _format_keywords,
)

#: Bumped when ``_SYSTEM`` or the cover request shape changes. Version 2 added
#: ATS/trust keyword split, anti-generic self-check, and optional CoverAngles.
_COVER_PROMPT_VERSION = 3

#: Long dashes the model must never emit. Mechanical replacement is safe when one slips
#: through after a retry.
_LONG_DASHES = ("\u2012", "\u2013", "\u2014", "\u2015")

#: Phrase blocklist for AI-tell detection. Curated against ``style.DEFAULT_REWRITE_STYLE``
#: so it never blocks a verb the rewrite style recommends (e.g. "spearheaded").
_AI_PHRASES = (
    "delve",
    "tapestry",
    "testament to",
    "i am writing to apply",
    "in today's fast-paced",
    "moreover",
    "furthermore",
    "in conclusion",
    "it is worth noting",
    "seamless",
    "cutting-edge",
    "synergy",
    "passionate about",
    "excited about the opportunity",
    "resonates with",
    "wealth of experience",
    "proven track record",
    "hit the ground running",
    "deep dive",
    "unlock",
    "harness",
    "pivotal",
)

#: Structural patterns that read as template prose rather than a human voice.
_AI_STRUCTURAL = (
    re.compile(r"\bnot just\b.+\bbut\b", re.IGNORECASE),
    re.compile(r"\bit is not about\b.+\bit is about\b", re.IGNORECASE),
)

#: First-person verbs that mark a sentence as a resume claim worth checking.
_FIRST_PERSON_VERB = re.compile(
    r"\b(?:I|i)'?(?:ve|m|d)?\s+"
    r"(?:built|designed|developed|engineered|led|managed|created|implemented|"
    r"improved|increased|reduced|achieved|delivered|shipped|trained|mentored|"
    r"optimized|optimised|launched|deployed|wrote|coded|programmed|researched|"
    r"analyzed|analysed|worked|contributed|helped|used|applied)\b"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


_SYSTEM = """\
You draft the body paragraphs of a cover letter for one specific job application.

The candidate's resume content and the job posting are supplied. Select two or three
experiences from what is on the tailored resume and connect them to the employer's stated
needs. Write in first person, in complete paragraphs.

Absolute rules:
- Never state a skill, tool, technology, employer, title, date, metric, or claim that is \
not present in the provided resume content or the job posting. Do not infer seniority, \
and do not invent a reason for wanting this company.
- Preserve every number exactly as written in the source. Do not round or derive figures.
- The company name, its location, and any addressee name must appear verbatim in the job \
posting. If the posting does not name one, leave that field empty; code omits it.
- Never write an em dash, en dash, or any other long dash. Use a comma, a colon, a \
semicolon, or two sentences.
- Never begin two consecutive sentences with "I".
- Return body paragraphs only. Letterhead, date, inside address, salutation, closing, and \
signature are filled in by code.
- Stay inside the given word band.
- A sentence that could appear unchanged in any cover letter for any company must be \
rewritten until it names this employer, this role, or a concrete fact from the posting \
or the tailored resume.

Voice
- Lead with what was done, not how it felt. Reach for a number, percentage, or concrete \
outcome before any general claim.
- Plain, direct sentences. Use technical vocabulary naturally, without over-explaining it \
and without reaching for jargon that adds nothing.
- Confident and matter-of-fact. No hedging such as "I believe" or "I think I could", and \
no inflated enthusiasm.
- Do not claim unearned traits such as passionate, hardworking, or team player. If a \
trait matters, prove it with a result.
- Mostly short declarative sentences, with one longer sentence per paragraph for rhythm. \
Never more than one subordinate clause deep.
- Frame everything around what the employer needs rather than what the candidate wants.

Keywords
- Treat must-have technical keywords as ATS-critical: when the tailored resume honestly \
supports one, mirror the posting's own wording for it in the body.
- Treat soft skills and nice-to-haves as trust signals for a human reader: show them \
through the work rather than naming them as traits.

Structure, four paragraphs, about 350 words
- Opening: name the role and open on something concrete. Never "I am writing to apply for".
- Body 1: connect the single most relevant experience to the employer's top stated need.
- Body 2: one quantified accomplishment addressing a second need, in two or three tight \
sentences.
- Close: a confident, specific call to action. Not "I hope to hear from you".
- Select two or three experiences in total. Never recap the whole resume.
- Mirror the posting's own verbs and vocabulary only where the source honestly supports it.

Candidate positioning
- Derive the candidate's focus from the tailored resume and the posting. Do not invent a \
specialty, a career goal, or a name the resume does not state.

Return a JSON object with company, company_location, addressee, and paragraphs (a list of \
body paragraph strings). Do not return salutation, closing, or signature.
"""

_CORE_RULES = """\
- Never state a skill, tool, technology, employer, title, date, metric, or claim that is \
not present in the provided resume content or the job posting. Do not infer seniority, \
and do not invent a reason for wanting this company.
- Preserve every number exactly as written in the source. Do not round or derive figures.
- The company name, its location, and any addressee name must appear verbatim in the job \
posting. If the posting does not name one, leave that field empty; code omits it.
- Never write an em dash, en dash, or any other long dash. Use a comma, a colon, a \
semicolon, or two sentences.
- Never begin two consecutive sentences with "I".
- Return body paragraphs only. Letterhead, date, inside address, salutation, closing, and \
signature are filled in by code.
- Stay inside the given word band.
- A sentence that could appear unchanged in any cover letter for any company must be \
rewritten until it names this employer, this role, or a concrete fact from the posting \
or the tailored resume.
"""

_RETURN_SHAPE = """\
Return a JSON object with company, company_location, addressee, and paragraphs (a list of \
body paragraph strings). Do not return salutation, closing, or signature.
"""

_RETRY_INSTRUCTION = """\
Your previous draft failed one or more checks listed below. Rewrite the body paragraphs \
only. Fix every listed issue. Do not add facts not present in the resume content or job \
posting. Do not use em dashes or en dashes.
"""


def locked_core_rules() -> str:
    """Return the non-editable cover-letter rules for display in the settings UI."""
    return _CORE_RULES.strip()


def _system() -> str:
    """Assemble the cover-letter system prompt, honoring any active style override."""
    if not style.is_overridden("cover"):
        return _SYSTEM
    style_block = style.active("cover").strip()
    if style_block and not style_block.endswith("\n"):
        style_block += "\n"
    return (
        "You draft the body paragraphs of a cover letter for one specific job application.\n\n"
        "The candidate's resume content and the job posting are supplied. Select two or three "
        "experiences from what is on the tailored resume and connect them to the employer's "
        "stated needs. Write in first person, in complete paragraphs.\n\n"
        "Absolute rules:\n"
        f"{_CORE_RULES}"
        f"{style_block}\n"
        f"{_RETURN_SHAPE}"
    )


class CoverLetterLLM(BaseModel):
    """Model output for one cover letter. Strings only; no layout, no hard facts."""

    company: str = ""
    company_location: str = ""
    addressee: str = ""
    paragraphs: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CoverAngles:
    """Optional per-application angle inputs for the cover letter.

    Separate from ``instruction`` on purpose: a non-empty instruction skips cache
    read, cache write, and the guard retry. Angles are durable per-application
    inputs that must stay cacheable and guarded. All fields optional — absent,
    behaviour is byte-identical to a run without angles (aside from the prompt
    version bump).
    """

    why_company: str = ""
    problem: str = ""
    approach: str = ""
    tone: str = ""

    def is_empty(self) -> bool:
        """True when every field is blank."""
        return not any(
            (
                self.why_company.strip(),
                self.problem.strip(),
                self.approach.strip(),
                self.tone.strip(),
            )
        )

    def cache_payload(self) -> str:
        """Stable string folded into the cover-letter cache key."""
        return "\n".join(
            [
                self.why_company.strip(),
                self.problem.strip(),
                self.approach.strip(),
                self.tone.strip(),
            ]
        )

    def prompt_block(self) -> str:
        """XML block for the user message, or empty string when nothing is set."""
        if self.is_empty():
            return ""
        parts: list[str] = ["<angles>"]
        if self.why_company.strip():
            parts.append(f"  <why_company>{self.why_company.strip()}</why_company>")
        if self.problem.strip():
            parts.append(f"  <problem>{self.problem.strip()}</problem>")
        if self.approach.strip():
            parts.append(f"  <approach>{self.approach.strip()}</approach>")
        if self.tone.strip():
            parts.append(f"  <tone>{self.tone.strip()}</tone>")
        parts.append("</angles>")
        return "\n".join(parts)


def _genericness_offenders(
    paragraphs: list[str],
    *,
    company: str,
    jd_text: str,
) -> list[str]:
    """Soft offenders when no body paragraph names the company or a JD phrase.

    Soft (not hard): surfaces as a warning without triggering a retry, matching
    phrase-level AI tells.
    """
    body = "\n".join(paragraphs).lower()
    if company.strip() and company.strip().lower() in body:
        return []
    # A short distinctive phrase from the posting — first 4+ letter token sequence
    # of length >= 2 that appears in both. Cheap proxy for "mentions the JD".
    jd_tokens = [t.lower() for t in _TOKEN.findall(jd_text) if len(t) >= 4]
    for i in range(len(jd_tokens) - 1):
        phrase = f"{jd_tokens[i]} {jd_tokens[i + 1]}"
        if phrase in body:
            return []
    return ["generic: no body paragraph names the company or a posting phrase"]


@dataclass
class CoverLetter:
    """Full cover-letter artifact for one tailoring run."""

    company: str = ""
    company_location: str = ""
    addressee: str = ""
    paragraphs: list[str] = field(default_factory=list)
    salutation: str = ""
    closing: str = "Sincerely,"
    signature: str = ""
    inside_address: list[str] = field(default_factory=list)
    date: str = ""
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    word_count: int = 0
    docx_path: Path | None = None
    pdf_path: Path | None = None


def ai_tells(text: str) -> list[str]:
    """Return AI-tell offenders found in ``text`` (long dashes, phrases, structures)."""
    offenders: list[str] = []
    lowered = text.lower()
    for dash in _LONG_DASHES:
        if dash in text:
            offenders.append(f"long dash {dash!r}")
    for phrase in _AI_PHRASES:
        if phrase in lowered:
            offenders.append(f"phrase {phrase!r}")
    for pattern in _AI_STRUCTURAL:
        if pattern.search(text):
            offenders.append(f"structure {pattern.pattern!r}")
    return list(dict.fromkeys(offenders))


def consecutive_first_person(paragraphs: list[str]) -> list[str]:
    """Return descriptions of consecutive sentences that both open with "I"."""
    offenders: list[str] = []
    for para in paragraphs:
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(para.strip()) if s.strip()]
        for prev, curr in zip(sentences, sentences[1:]):
            if prev.startswith("I ") and curr.startswith("I "):
                offenders.append(f'consecutive "I" after "{prev[:40]}..."')
    return offenders


def _replace_long_dashes(text: str) -> str:
    """Replace any surviving long dash with a comma and a space."""
    for dash in _LONG_DASHES:
        text = text.replace(dash, ", ")
    return re.sub(r",\s+,", ", ", text)


def _word_count(paragraphs: list[str]) -> int:
    """Count words across all body paragraphs."""
    return sum(len(p.split()) for p in paragraphs)


def _verbatim_in_jd(value: str, jd_text: str) -> bool:
    """Return True when ``value`` appears verbatim in the posting (case-insensitive)."""
    stripped = value.strip()
    if not stripped:
        return True
    return stripped.lower() in jd_text.lower()


def _numbers_not_in_source(
    text: str,
    source_bullets: list[Bullet],
    jd_text: str,
) -> list[str]:
    """Return number-bearing tokens in ``text`` absent from bullets or the posting."""
    allowed: set[str] = set()
    for match in _TOKEN.finditer(jd_text):
        term = match.group(0)
        if _HAS_DIGIT.search(term):
            allowed.add(term.lower())
    for bullet in source_bullets:
        for src in (bullet.text, " ".join(bullet.tags)):
            for match in _TOKEN.finditer(src):
                term = match.group(0)
                if _HAS_DIGIT.search(term):
                    allowed.add(term.lower())

    offenders: list[str] = []
    for match in _TOKEN.finditer(text):
        term = match.group(0)
        if _HAS_DIGIT.search(term) and term.lower() not in allowed:
            offenders.append(term)
    return list(dict.fromkeys(offenders))


def _claim_fabrication_offenders(
    paragraphs: list[str],
    source_bullets: list[Bullet],
    *,
    first_person_only: bool = True,
) -> list[str]:
    """Run the fabrication guard on claim sentences in ``paragraphs``.

    When ``first_person_only`` is True (the cover-letter default), only sentences that
    match ``_FIRST_PERSON_VERB`` are checked — company-description prose is exempt.
    When False (application-answer verification), every sentence is checked, because
    resume-voice answers ("Led a team of three…") have no first-person pronoun and would
    otherwise sail through.
    """
    offenders: list[str] = []
    for para in paragraphs:
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(para.strip()) if s.strip()]
        for sentence in sentences:
            if first_person_only and not _FIRST_PERSON_VERB.search(sentence):
                continue
            offenders.extend(_check_fabrication(source_bullets, sentence))
    return list(dict.fromkeys(offenders))


_CONTEXT_BULLET_ID = "__cover_resume_context__"


def _resume_context_bullet(resume: MasterResume) -> Bullet:
    """Pack resume-level proper nouns into one synthetic bullet for the claim guard.

    Employer names, titles, schools, and project names live on entry headers, not in
    bullet text, so ``rewrite._check_fabrication`` would otherwise reject them. Used by
    cover-letter drafting and by ``check_claims`` (application-answer verification).
    Per-bullet rewrite guards keep their narrow contract — they do not use this.
    """
    parts: list[str] = []
    for section in resume.sections:
        parts.append(section.title)
        if section.kind == "experience":
            for entry in section.entries:
                parts.extend([entry.company, entry.title, entry.location])
        elif section.kind == "project":
            for entry in section.entries:
                parts.append(entry.name)
                parts.extend(entry.tech)
        elif section.kind == "education":
            for entry in section.entries:
                parts.extend([entry.school, entry.degree, entry.location])
                parts.extend(entry.coursework)
        elif section.kind == "skills":
            for group in section.entries:
                parts.append(group.label)
                parts.extend(group.items)
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return Bullet(id=_CONTEXT_BULLET_ID, text=text, tags=["resume-context"])


def _source_bullets(resume: MasterResume, bullets: dict[str, str]) -> list[Bullet]:
    """Return ``Bullet`` objects for every tailored id, with rewritten text applied."""
    out: list[Bullet] = []
    for bullet in resume.all_bullets():
        if bullet.id not in bullets:
            continue
        rewritten = bullets[bullet.id]
        out.append(bullet.model_copy(update={"text": rewritten}))
    out.append(_resume_context_bullet(resume))
    return out


@dataclass(frozen=True)
class ClaimCheck:
    """Result of checking free-text application prose against a run's tailored bullets."""

    ok: bool
    unsupported_terms: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)


def check_claims(
    resume: MasterResume,
    bullets: dict[str, str],
    jd_text: str,
    text: str,
) -> ClaimCheck:
    """Check application-answer prose against tailored bullets and the posting.

    Unlike the cover-letter path (which only inspects first-person claim sentences),
    every sentence is checked — application answers are often written in resume voice
    without "I". Numbers are allowed when present in the tailored bullets or the JD.
    Pure: no LLM, no disk writes.
    """
    source = _source_bullets(resume, bullets)
    terms = _claim_fabrication_offenders(
        [text], source, first_person_only=False
    )
    numbers = _numbers_not_in_source(text, source, jd_text)
    return ClaimCheck(
        ok=not terms and not numbers,
        unsupported_terms=terms,
        unsupported_numbers=numbers,
    )


def _validate_posting_fields(
    llm_result: CoverLetterLLM,
    jd_text: str,
) -> tuple[str, str, str, list[str]]:
    """Blank posting-sourced fields not found verbatim in the JD; return warnings."""
    warnings: list[str] = []
    company = llm_result.company.strip()
    location = llm_result.company_location.strip()
    addressee = llm_result.addressee.strip()

    if company and not _verbatim_in_jd(company, jd_text):
        warnings.append(f"Company {company!r} not found in posting; omitted")
        company = ""
    if location and not _verbatim_in_jd(location, jd_text):
        warnings.append(f"Location {location!r} not found in posting; omitted")
        location = ""
    if addressee and not _verbatim_in_jd(addressee, jd_text):
        warnings.append(f"Addressee {addressee!r} not found in posting; omitted")
        addressee = ""
    return company, location, addressee, warnings


@dataclass
class _GuardResult:
    """Outcome of running the guard ladder on one draft."""

    paragraphs: list[str]
    hard_offenders: list[str]
    soft_offenders: list[str]
    warnings: list[str]


def _accept_letter(
    llm_result: CoverLetterLLM,
    *,
    source_bullets: list[Bullet],
    jd_text: str,
    word_band: tuple[int, int],
) -> _GuardResult:
    """Run the full guard ladder on one model draft."""
    company, location, addressee, field_warnings = _validate_posting_fields(
        llm_result, jd_text
    )
    paragraphs = [p.strip() for p in llm_result.paragraphs if p.strip()]
    body = "\n".join(paragraphs)

    hard: list[str] = []
    soft: list[str] = []
    warnings = list(field_warnings)

    hard.extend(_numbers_not_in_source(body, source_bullets, jd_text))
    hard.extend(_claim_fabrication_offenders(paragraphs, source_bullets))

    for tell in ai_tells(body):
        if tell.startswith("long dash"):
            hard.append(tell)
        else:
            soft.append(tell)

    hard.extend(consecutive_first_person(paragraphs))
    soft.extend(
        _genericness_offenders(paragraphs, company=company, jd_text=jd_text)
    )

    count = _word_count(paragraphs)
    lo, hi = word_band
    if count < lo or count > hi:
        hard.append(f"word count {count} outside band {lo}-{hi}")

    # Mechanical fix for long dashes that survived a retry.
    cleaned = [_replace_long_dashes(p) for p in paragraphs]
    if cleaned != paragraphs:
        warnings.append("Replaced long dashes with commas")
        paragraphs = cleaned

    return _GuardResult(
        paragraphs=paragraphs,
        hard_offenders=hard,
        soft_offenders=soft,
        warnings=warnings,
    )


def _format_education(resume: MasterResume) -> str:
    """Format education entries for the cover-letter user message."""
    lines: list[str] = []
    for edu in resume.education:
        parts = [edu.school, edu.degree, edu.dates]
        if edu.gpa and edu.show_gpa:
            parts.append(f"GPA {edu.gpa}")
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines) or "(none)"


def _format_skills(resume: MasterResume) -> str:
    """Format skills groups for the cover-letter user message."""
    lines: list[str] = []
    for group in resume.skills:
        items = ", ".join(group.items)
        if items:
            lines.append(f"{group.label}: {items}")
    return "\n".join(lines) or "(none)"


def _format_tailored_entries(
    resume: MasterResume,
    bullets: dict[str, str],
) -> str:
    """Build the tailored-resume block for the cover-letter user message."""
    blocks: list[str] = []
    for section in resume.entry_sections:
        for entry in section.entries:
            entry_bullets = [
                (b.id, bullets[b.id])
                for b in entry.bullets
                if b.id in bullets
            ]
            if not entry_bullets:
                continue
            source_bullet = resume.bullet_by_id(entry_bullets[0][0])
            if hasattr(entry, "company"):
                label = f"{entry.title} at {entry.company}"
            else:
                label = getattr(entry, "name", section.title)
            bullet_lines = "\n".join(
                f"    <bullet id={bid!r}>\n"
                f"      <current>{text}</current>\n"
                f"      <permitted_skills>{', '.join((resume.bullet_by_id(bid) or source_bullet).tags)}</permitted_skills>\n"
                f"    </bullet>"
                for bid, text in entry_bullets
            )
            blocks.append(
                f"<entry>\n  <role>{label}</role>\n  <bullets>\n{bullet_lines}\n  </bullets>\n</entry>"
            )
    return "\n".join(blocks) or "(no tailored bullets)"


def _cache_path(
    bullets: dict[str, str],
    requirements: JobRequirements,
    *,
    jd_text: str,
    word_band: tuple[int, int],
    instruction: str = "",
    angles: CoverAngles | None = None,
) -> Path:
    """Cache key covering everything the cover letter depends on."""
    angles = angles or CoverAngles()
    payload = "\n".join(
        [
            str(_COVER_PROMPT_VERSION),
            config.fingerprint("cover"),
            style.digest("cover"),
            f"{word_band[0]}-{word_band[1]}",
            instruction,
            angles.cache_payload(),
            requirements.model_dump_json(),
            jd_text,
            *(f"{bid}:{text}" for bid, text in sorted(bullets.items())),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.cover.json"


def _build_salutation(addressee: str) -> str:
    """Build the letter salutation from an optional named addressee."""
    if addressee.strip():
        return f"Dear {addressee.strip()},"
    return "Dear Hiring Manager,"


def _build_inside_address(company: str, company_location: str) -> list[str]:
    """Build the inside-address lines from validated posting fields."""
    lines: list[str] = []
    if company:
        lines.append(company)
    if company_location:
        lines.append(company_location)
    return lines


def _format_date_long(when: date | None = None) -> str:
    """Format a date as a long English month-day-year string."""
    when = when or date.today()
    return when.strftime("%B %d, %Y").replace(" 0", " ")


def format_markdown(letter: CoverLetter) -> str:
    """Render the cover letter as plain text suitable for copy-all or a .md download."""
    lines: list[str] = []
    if letter.date:
        lines.append(letter.date)
        lines.append("")
    for line in letter.inside_address:
        lines.append(line)
    if letter.inside_address:
        lines.append("")
    lines.append(letter.salutation)
    lines.append("")
    lines.extend(letter.paragraphs)
    lines.append("")
    lines.append(letter.closing)
    lines.append(letter.signature)
    return "\n".join(lines)


def _call_model(
    *,
    resume: MasterResume,
    requirements: JobRequirements,
    bullets: dict[str, str],
    jd_text: str,
    word_band: tuple[int, int],
    instruction: str = "",
    angles: CoverAngles | None = None,
    retry_offenders: list[str] | None = None,
    previous_paragraphs: list[str] | None = None,
) -> CoverLetterLLM:
    """Issue one cover-letter LLM call and return the parsed result."""
    lo, hi = word_band
    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    user_parts = [
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n",
        f"<word_band>{lo}-{hi}</word_band>\n\n",
        f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n",
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n",
        f"<education>\n{_format_education(resume)}\n</education>\n\n",
        f"<skills>\n{_format_skills(resume)}\n</skills>\n\n",
        f"<tailored_resume>\n{_format_tailored_entries(resume, bullets)}\n</tailored_resume>\n\n",
        f"<job_posting>\n{jd_text.strip()}\n</job_posting>",
    ]
    angles_block = (angles or CoverAngles()).prompt_block()
    if angles_block:
        # Distinct from <extra_instruction>: angles are durable and cacheable.
        user_parts.append(f"\n\n{angles_block}")
    if instruction.strip():
        user_parts.append(f"\n\n<extra_instruction>\n{instruction.strip()}\n</extra_instruction>")
    if retry_offenders:
        prev = "\n\n".join(previous_paragraphs or [])
        offenders = "\n".join(f"  - {o}" for o in retry_offenders)
        user_parts.append(
            f"\n\n<previous_draft>\n{prev}\n</previous_draft>\n\n"
            f"<issues>\n{offenders}\n</issues>\n\n{_RETRY_INSTRUCTION}"
        )
    user = "".join(user_parts)

    client = llm.client_for("cover")
    response = client.messages.parse(
        model=config.model_for("cover"),
        max_tokens=config.max_tokens_for("cover"),
        system=_system(),
        messages=[{"role": "user", "content": user}],
        output_format=CoverLetterLLM,
        output_config={"effort": config.effort_for("cover")},
    )
    result = response.parsed_output
    if result is None:
        raise RuntimeError(
            f"Model did not return a parseable cover letter "
            f"(stop_reason={response.stop_reason!r})."
        )
    return result


def draft_letter(
    resume: MasterResume,
    requirements: JobRequirements,
    bullets: dict[str, str],
    jd_text: str,
    *,
    use_cache: bool = True,
    instruction: str = "",
    angles: CoverAngles | None = None,
    on_event: events.ProgressCallback | None = None,
) -> CoverLetter:
    """Draft a cover letter from the tailored bullets and job posting.

    The LLM returns body paragraphs plus posting-sourced fields; code assembles the
    salutation, inside address, date, closing, and signature. One targeted retry runs when
    the guard finds hard offenders. Surviving soft offenders (phrase-level AI tells) become
    warnings rather than failing the stage.

    ``angles`` is a separate, cacheable parameter — do not route durable per-application
    inputs through ``instruction``, which deliberately bypasses cache and the guard retry.
    """
    word_band = config.COVER_WORD_BAND
    model_label = config.backend_for("cover").label()
    source_bullets = _source_bullets(resume, bullets)
    angles = angles or CoverAngles()

    if not bullets:
        events.emit(on_event, "cover", "No tailored bullets for cover letter")
        return CoverLetter(warnings=["No tailored bullets to write from"], model=model_label)

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(
        bullets,
        requirements,
        jd_text=jd_text,
        word_band=word_band,
        instruction=instruction,
        angles=angles,
    )

    llm_result: CoverLetterLLM | None = None
    if use_cache and cache_path.exists() and not instruction.strip():
        events.emit(on_event, "cover", "Reusing cached cover letter", cached=True)
        llm_result = CoverLetterLLM.model_validate_json(
            cache_path.read_text(encoding="utf-8")
        )
    else:
        events.emit(
            on_event,
            "cover",
            "Drafting cover letter",
            cached=False,
            model=config.model_for("cover"),
        )
        llm_result = _call_model(
            resume=resume,
            requirements=requirements,
            bullets=bullets,
            jd_text=jd_text,
            word_band=word_band,
            instruction=instruction,
            angles=angles,
        )
        if not instruction.strip():
            cache_path.write_text(llm_result.model_dump_json(indent=2), encoding="utf-8")

    accepted = _accept_letter(
        llm_result,
        source_bullets=source_bullets,
        jd_text=jd_text,
        word_band=word_band,
    )

    if accepted.hard_offenders and not instruction.strip():
        events.emit(
            on_event,
            "cover",
            "Retrying cover letter after guard failures",
            offenders=len(accepted.hard_offenders),
        )
        llm_result = _call_model(
            resume=resume,
            requirements=requirements,
            bullets=bullets,
            jd_text=jd_text,
            word_band=word_band,
            angles=angles,
            retry_offenders=accepted.hard_offenders,
            previous_paragraphs=accepted.paragraphs,
        )
        accepted = _accept_letter(
            llm_result,
            source_bullets=source_bullets,
            jd_text=jd_text,
            word_band=word_band,
        )
        cache_path.write_text(llm_result.model_dump_json(indent=2), encoding="utf-8")

    company, location, addressee, _ = _validate_posting_fields(llm_result, jd_text)
    warnings = accepted.warnings + [
        f"AI tell: {o}" for o in accepted.soft_offenders
    ]
    if accepted.hard_offenders:
        warnings.append(
            "Guard issues remain after retry: " + "; ".join(accepted.hard_offenders)
        )

    letter = CoverLetter(
        company=company,
        company_location=location,
        addressee=addressee,
        paragraphs=accepted.paragraphs,
        salutation=_build_salutation(addressee),
        signature=resume.contact.name,
        inside_address=_build_inside_address(company, location),
        date=_format_date_long(),
        warnings=warnings,
        model=model_label,
        word_count=_word_count(accepted.paragraphs),
    )
    return letter


def render_cover_letter(
    resume: MasterResume,
    letter: CoverLetter,
    *,
    out: Path,
) -> CoverLetter:
    """Render ``letter`` to ``out`` and attempt PDF conversion plus a one-page check."""
    from . import cover_template, render

    cover_template.ensure_cover_template()
    docx_path = render.render_letter(
        resume,
        letter,
        out=out,
        contact_fields=list(config.COVER_CONTACT_FIELDS),
    )
    letter.docx_path = docx_path
    pdf_path = out.with_suffix(".pdf")
    try:
        render.to_pdf(docx_path, pdf_path)
        letter.pdf_path = pdf_path
        pages, _lines = render.measure_detail(docx_path)
        if pages > 1:
            letter.warnings.append(
                f"Cover letter rendered to {pages} pages (expected 1)"
            )
    except RuntimeError as exc:
        letter.warnings.append(f"PDF preview unavailable: {exc}")
    return letter
