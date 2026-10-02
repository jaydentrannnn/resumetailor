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
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..content import industries, style
from ..content.data import Bullet, MasterResume
from ..infra import llm
from . import coverletter_format, coverletter_models, coverletter_style, events
from .fabrication import _check_fabrication
from .jd import JobRequirements
from .rewrite_prompts import _format_keywords

#: Bumped when ``_SYSTEM`` or the cover request shape changes. Version 2 added
#: ATS/trust keyword split, anti-generic self-check, and optional CoverAngles.
_COVER_PROMPT_VERSION = 4


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
    return industries.core("cover", _CORE_RULES).strip()


def _system() -> str:
    """Assemble the cover-letter system prompt, honoring any active style override."""
    if not style.is_overridden("cover"):
        return _SYSTEM
    style_block = style.active("cover").strip()
    if style_block and not style_block.endswith("\n"):
        style_block += "\n"
    return industries.system("cover", (
        "You draft the body paragraphs of a cover letter for one specific job application.\n\n"
        "The candidate's resume content and the job posting are supplied. Select two or three "
        "experiences from what is on the tailored resume and connect them to the employer's "
        "stated needs. Write in first person, in complete paragraphs.\n\n"
        "Absolute rules:\n"
        f"{_CORE_RULES}"
        f"{style_block}\n"
        f"{_RETURN_SHAPE}"
    ))


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
        sentences = [
            s.strip() for s in coverletter_style._SENTENCE_SPLIT.split(para.strip()) if s.strip()
        ]
        for sentence in sentences:
            if first_person_only and not coverletter_style._FIRST_PERSON_VERB.search(sentence):
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
    numbers = coverletter_style._numbers_not_in_source(text, source, jd_text)
    return ClaimCheck(
        ok=not terms and not numbers,
        unsupported_terms=terms,
        unsupported_numbers=numbers,
    )


def _validate_posting_fields(
    llm_result: coverletter_models.CoverLetterLLM,
    jd_text: str,
) -> tuple[str, str, str, list[str]]:
    """Blank posting-sourced fields not found verbatim in the JD; return warnings."""
    warnings: list[str] = []
    company = llm_result.company.strip()
    location = llm_result.company_location.strip()
    addressee = llm_result.addressee.strip()

    if company and not coverletter_style._verbatim_in_jd(company, jd_text):
        warnings.append(f"Company {company!r} not found in posting; omitted")
        company = ""
    if location and not coverletter_style._verbatim_in_jd(location, jd_text):
        warnings.append(f"Location {location!r} not found in posting; omitted")
        location = ""
    if addressee and not coverletter_style._verbatim_in_jd(addressee, jd_text):
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
    llm_result: coverletter_models.CoverLetterLLM,
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

    hard.extend(coverletter_style._numbers_not_in_source(body, source_bullets, jd_text))
    hard.extend(_claim_fabrication_offenders(paragraphs, source_bullets))

    for tell in coverletter_style.ai_tells(body):
        if tell.startswith("long dash"):
            hard.append(tell)
        else:
            soft.append(tell)

    hard.extend(coverletter_style.consecutive_first_person(paragraphs))
    soft.extend(
        coverletter_models._genericness_offenders(paragraphs, company=company, jd_text=jd_text)
    )

    count = coverletter_style._word_count(paragraphs)
    lo, hi = word_band
    if count < lo or count > hi:
        hard.append(f"word count {count} outside band {lo}-{hi}")

    # Mechanical fix for long dashes that survived a retry.
    cleaned = [coverletter_style._replace_long_dashes(p) for p in paragraphs]
    if cleaned != paragraphs:
        warnings.append("Replaced long dashes with commas")
        paragraphs = cleaned

    return _GuardResult(
        paragraphs=paragraphs,
        hard_offenders=hard,
        soft_offenders=soft,
        warnings=warnings,
    )


def _cache_path(
    bullets: dict[str, str],
    requirements: JobRequirements,
    *,
    jd_text: str,
    word_band: tuple[int, int],
    instruction: str = "",
    angles: coverletter_models.CoverAngles | None = None,
) -> Path:
    """Cache key covering everything the cover letter depends on."""
    angles = angles or coverletter_models.CoverAngles()
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


def _call_model(
    *,
    resume: MasterResume,
    requirements: JobRequirements,
    bullets: dict[str, str],
    jd_text: str,
    word_band: tuple[int, int],
    instruction: str = "",
    angles: coverletter_models.CoverAngles | None = None,
    retry_offenders: list[str] | None = None,
    previous_paragraphs: list[str] | None = None,
) -> coverletter_models.CoverLetterLLM:
    """Issue one cover-letter LLM call and return the parsed result."""
    lo, hi = word_band
    notes = "\n".join(f"  - {n}" for n in requirements.domain_notes) or "  (none)"
    user_parts = [
        f"<role>{requirements.title} ({requirements.seniority})</role>\n\n",
        f"<word_band>{lo}-{hi}</word_band>\n\n",
        f"<what_the_role_involves>\n{notes}\n</what_the_role_involves>\n\n",
        f"<keywords_to_mirror>\n{_format_keywords(requirements)}\n</keywords_to_mirror>\n\n",
        f"<education>\n{coverletter_format._format_education(resume)}\n</education>\n\n",
        f"<skills>\n{coverletter_format._format_skills(resume)}\n</skills>\n\n",
        f"<tailored_resume>\n{coverletter_format._format_tailored_entries(resume, bullets)}\n</tailored_resume>\n\n",
        f"<job_posting>\n{jd_text.strip()}\n</job_posting>",
    ]
    angles_block = (angles or coverletter_models.CoverAngles()).prompt_block()
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
        output_format=coverletter_models.CoverLetterLLM,
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
    angles: coverletter_models.CoverAngles | None = None,
    on_event: events.ProgressCallback | None = None,
) -> coverletter_models.CoverLetter:
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
    angles = angles or coverletter_models.CoverAngles()

    if not bullets:
        events.emit(on_event, "cover", "No tailored bullets for cover letter")
        return coverletter_models.CoverLetter(
            warnings=["No tailored bullets to write from"], model=model_label
        )

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(
        bullets,
        requirements,
        jd_text=jd_text,
        word_band=word_band,
        instruction=instruction,
        angles=angles,
    )

    llm_result: coverletter_models.CoverLetterLLM | None = None
    if use_cache and cache_path.exists() and not instruction.strip():
        events.emit(on_event, "cover", "Reusing cached cover letter", cached=True)
        llm_result = coverletter_models.CoverLetterLLM.model_validate_json(
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

    letter = coverletter_models.CoverLetter(
        company=company,
        company_location=location,
        addressee=addressee,
        paragraphs=accepted.paragraphs,
        salutation=coverletter_format._build_salutation(addressee),
        signature=resume.contact.name,
        inside_address=coverletter_format._build_inside_address(company, location),
        date=coverletter_format._format_date_long(),
        warnings=warnings,
        model=model_label,
        word_count=coverletter_style._word_count(accepted.paragraphs),
    )
    return letter


def render_cover_letter(
    resume: MasterResume,
    letter: coverletter_models.CoverLetter,
    *,
    out: Path,
) -> coverletter_models.CoverLetter:
    """Render ``letter`` to ``out`` and attempt PDF conversion plus a one-page check."""
    from ..document import cover_template, render

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
