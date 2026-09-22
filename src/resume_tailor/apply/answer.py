"""Guarded free-text answers for ATS application questions.

The only LLM call in the apply package. Profile ``custom_answers`` short-circuit without
a model round-trip; otherwise one ``answer``-purpose call runs with a locked-core prompt,
then ``coverletter.check_claims`` verifies the draft. Fabricating answers are retried once,
then discarded rather than returned unguarded.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config, events, llm
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.coverletter import check_claims
from resume_tailor.data import MasterResume
from resume_tailor.jd import JobRequirements

#: Bumped when ``_SYSTEM`` or the request shape changes so cached answers invalidate.
_ANSWER_PROMPT_VERSION = 1

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class AnswerLLM(BaseModel):
    """Schema-validated model output for one application answer."""

    answer: str = ""


@dataclass
class AnswerResult:
    """Outcome of answering one ATS free-text question."""

    answer: str
    offenders: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = "llm"
    model: str = ""


_SYSTEM = """\
You answer one job-application question using only the candidate information provided.

Absolute rules:
- Never invent employers, titles, tools, technologies, metrics, dates, or achievements.
- Preserve every number exactly as written in the source bullets or headers.
- Use plain prose in complete sentences. Do not use em dashes or en dashes.
- Stay within the requested character limit.
- If the provided material does not support a truthful answer, say briefly that the \
information is not available in the resume content supplied.
"""


def normalize_question(question: str) -> str:
    """Lowercase and strip punctuation for ``custom_answers`` matching."""
    text = question.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _profile_answer(question: str, profile: ApplicantProfile) -> str | None:
    """Return a canned answer when the question matches ``custom_answers``."""
    norm_q = normalize_question(question)
    for key, answer in profile.custom_answers.items():
        norm_key = normalize_question(key)
        if not norm_key:
            continue
        if norm_key in norm_q or norm_q in norm_key:
            return answer.strip()
    return None


def _format_bullets(resume: MasterResume, bullets: dict[str, str]) -> str:
    """Render tailored bullets and entry headers for the user message."""
    blocks: list[str] = []
    for section in resume.entry_sections:
        for entry in section.entries:
            entry_bullets = [
                (bullet.id, bullets[bullet.id])
                for bullet in entry.bullets
                if bullet.id in bullets
            ]
            if not entry_bullets:
                continue
            if hasattr(entry, "company"):
                header = f"{entry.title} at {entry.company}"
                if getattr(entry, "location", ""):
                    header += f" ({entry.location})"
            else:
                header = getattr(entry, "name", section.title)
            bullet_lines = "\n".join(f"- {text}" for _, text in entry_bullets)
            blocks.append(f"{header}\n{bullet_lines}")
    return "\n\n".join(blocks) or "(no tailored bullets)"


def _offenders_from_check(check) -> list[str]:
    """Flatten a ``ClaimCheck`` into a single offender list."""
    return list(dict.fromkeys([*check.unsupported_terms, *check.unsupported_numbers]))


def _truncate_at_sentence(text: str, max_chars: int) -> tuple[str, list[str]]:
    """Trim ``text`` to ``max_chars``, preferring a sentence boundary."""
    if len(text) <= max_chars:
        return text, []
    trimmed = text[:max_chars]
    best = -1
    for match in _SENTENCE_END.finditer(trimmed):
        best = match.start()
    if best > 0:
        return trimmed[: best + 1].strip(), ["truncated to fit character limit"]
    last_space = trimmed.rfind(" ")
    if last_space > max_chars // 2:
        return trimmed[:last_space].strip(), ["truncated to fit character limit"]
    return trimmed.strip(), ["truncated to fit character limit"]


def _cache_path(question: str, bullets: dict[str, str], *, max_chars: int) -> Path:
    """Return the cache file path for one guarded answer request."""
    payload = "\n".join(
        [
            str(_ANSWER_PROMPT_VERSION),
            config.fingerprint("answer"),
            str(max_chars),
            question,
            *(f"{key}:{bullets[key]}" for key in sorted(bullets)),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.answer.json"


def _call_model(
    *,
    question: str,
    resume: MasterResume,
    bullets: dict[str, str],
    requirements: JobRequirements | None,
    max_chars: int,
    jd_text: str,
    retry_offenders: list[str] | None = None,
) -> AnswerLLM:
    """Issue one ``answer``-purpose LLM call."""
    role_title = requirements.title if requirements else "(unknown role)"
    seniority = requirements.seniority if requirements else ""
    user_parts = [
        f"<question max_chars={max_chars}>\n{question.strip()}\n</question>",
        f"<role>{role_title} ({seniority})</role>" if seniority else f"<role>{role_title}</role>",
        f"<resume_content>\n{_format_bullets(resume, bullets)}\n</resume_content>",
    ]
    if jd_text.strip():
        user_parts.append(f"<job_posting_excerpt>\n{jd_text.strip()[:4000]}\n</job_posting_excerpt>")
    if retry_offenders:
        user_parts.append(
            "<retry>\n"
            "The previous draft contained unsupported claims: "
            f"{', '.join(retry_offenders)}. "
            "Rewrite without them.\n</retry>"
        )
    client = llm.client_for("answer")
    response = client.messages.parse(
        model=config.model_for("answer"),
        max_tokens=config.max_tokens_for("answer"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
        output_format=AnswerLLM,
    )
    return response.parsed_output


def answer_question(
    question: str,
    *,
    resume: MasterResume,
    bullets: dict[str, str],
    requirements: JobRequirements | None = None,
    profile: ApplicantProfile,
    max_chars: int = 1500,
    jd_text: str = "",
    on_event: events.ProgressCallback | None = None,
    use_cache: bool = True,
) -> AnswerResult:
    """Answer one ATS question from profile canned text or a guarded LLM draft."""
    model_label = config.backend_for("answer").label()

    canned = _profile_answer(question, profile)
    if canned is not None:
        answer, warnings = _truncate_at_sentence(canned, max_chars)
        events.emit(on_event, "answer", "Using profile canned answer", cached=True)
        return AnswerResult(
            answer=answer,
            warnings=warnings,
            source="profile",
            model=model_label,
        )

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(question, bullets, max_chars=max_chars)
    if use_cache and cache_path.is_file():
        events.emit(on_event, "answer", "Reusing cached application answer", cached=True)
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return AnswerResult(
            answer=str(cached.get("answer", "")),
            offenders=list(cached.get("offenders", [])),
            warnings=list(cached.get("warnings", [])),
            source=str(cached.get("source", "llm")),
            model=str(cached.get("model", model_label)),
        )

    events.emit(on_event, "answer", "Drafting application answer", cached=False)
    draft = _call_model(
        question=question,
        resume=resume,
        bullets=bullets,
        requirements=requirements,
        max_chars=max_chars,
        jd_text=jd_text,
    )
    answer_text = draft.answer.strip()
    check = check_claims(resume, bullets, jd_text, answer_text)
    warnings: list[str] = []

    if not check.ok:
        offenders = _offenders_from_check(check)
        events.emit(
            on_event,
            "answer",
            "Retrying answer after unsupported claims",
            offenders=offenders,
        )
        retry = _call_model(
            question=question,
            resume=resume,
            bullets=bullets,
            requirements=requirements,
            max_chars=max_chars,
            jd_text=jd_text,
            retry_offenders=offenders,
        )
        answer_text = retry.answer.strip()
        check = check_claims(resume, bullets, jd_text, answer_text)
        if not check.ok:
            offenders = _offenders_from_check(check)
            warnings.append("Answer discarded after guard failure")
            result = AnswerResult(
                answer="",
                offenders=offenders,
                warnings=warnings,
                source="llm",
                model=model_label,
            )
            if use_cache:
                cache_path.write_text(
                    json.dumps(
                        {
                            "answer": result.answer,
                            "offenders": result.offenders,
                            "warnings": result.warnings,
                            "source": result.source,
                            "model": result.model,
                        },
                        ensure_ascii=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            return result

    answer_text, truncate_warnings = _truncate_at_sentence(answer_text, max_chars)
    warnings.extend(truncate_warnings)
    result = AnswerResult(
        answer=answer_text,
        warnings=warnings,
        source="llm",
        model=model_label,
    )
    if use_cache:
        cache_path.write_text(
            json.dumps(
                {
                    "answer": result.answer,
                    "offenders": result.offenders,
                    "warnings": result.warnings,
                    "source": result.source,
                    "model": result.model,
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    return result
