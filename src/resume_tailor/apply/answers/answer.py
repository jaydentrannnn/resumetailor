"""Guarded free-text answers for ATS application questions.

Profile ``custom_answers`` short-circuit without a model round-trip; otherwise one
``answer``-purpose call runs with a locked-core prompt, then ``coverletter.check_claims``
verifies the draft. Fabricating answers are retried once, then discarded rather than
returned unguarded. :func:`classify_questions` (the decision layer's fallback) names the
fact a choice question asks for; it never answers one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.answers import questions
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.content.data import MasterResume
from resume_tailor.infra import llm
from resume_tailor.pipeline import events
from resume_tailor.pipeline.coverletter import check_claims
from resume_tailor.pipeline.jd import JobRequirements

#: Bumped when ``_SYSTEM`` or the request shape changes so cached answers invalidate.
_ANSWER_PROMPT_VERSION = 2

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
- If the provided material does not support a truthful answer, return an empty answer.
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
        if norm_key == norm_q:
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


def _cache_path(
    question: str, bullets: dict[str, str], *, max_chars: int,
    resume: MasterResume, requirements: JobRequirements | None, jd_text: str,
    policy: str = "legacy",
) -> Path:
    """Return the cache file path for one guarded answer request."""
    payload = "\n".join(
        [
            f"{_ANSWER_PROMPT_VERSION}:job-context-v2",
            policy,
            config.fingerprint("answer"),
            str(max_chars),
            question,
            _format_bullets(resume, bullets),
            requirements.title if requirements else "",
            requirements.seniority if requirements else "",
            jd_text,
            *(f"{key}:{bullets[key]}" for key in sorted(bullets)),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.answer.json"


def _write_cache(path: Path, result: AnswerResult) -> None:
    """Persist one successful answer. Guard failures are never written — see callers."""
    path.write_text(
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


def _call_model(
    *,
    question: str,
    resume: MasterResume,
    bullets: dict[str, str],
    requirements: JobRequirements | None,
    max_chars: int,
    jd_text: str,
    retry_offenders: list[str] | None = None,
    deadline: float | None = None,
) -> AnswerLLM:
    """Issue one ``answer``-purpose LLM call."""
    user_parts = _request_parts(
        question=question, resume=resume, bullets=bullets,
        requirements=requirements, max_chars=max_chars, jd_text=jd_text,
        retry_offenders=retry_offenders,
    )
    client = llm.client_for("answer")
    if deadline is not None:
        timeout = max(1.0, min(60.0, deadline - time.monotonic()))
        if hasattr(client, "timeout"):
            client.timeout = min(float(client.timeout), timeout)
        elif hasattr(client, "with_options"):
            client = client.with_options(timeout=timeout)
    response = client.messages.parse(
        model=config.model_for("answer"),
        max_tokens=config.max_tokens_for("answer"),
        system=_SYSTEM,
        messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
        output_format=AnswerLLM,
    )
    return response.parsed_output


def _request_parts(
    *, question: str, resume: MasterResume, bullets: dict[str, str],
    requirements: JobRequirements | None, max_chars: int, jd_text: str,
    retry_offenders: list[str] | None,
) -> list[str]:
    """Build the same plain-text request for sync and async transports."""
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
    return user_parts


async def _call_model_async(
    *, question: str, resume: MasterResume, bullets: dict[str, str],
    requirements: JobRequirements | None, max_chars: int, jd_text: str,
    retry_offenders: list[str] | None = None, deadline: float,
) -> AnswerLLM:
    user_parts = _request_parts(
        question=question, resume=resume, bullets=bullets,
        requirements=requirements, max_chars=max_chars, jd_text=jd_text,
        retry_offenders=retry_offenders,
    )
    remaining = min(60.0, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError("Application answer exceeded its deadline")
    async with asyncio.timeout(remaining):
        async with llm.async_client_for("answer") as client:
            kwargs = {"deadline": deadline} if isinstance(client, llm._AsyncOpenAICompatClient) else {}  # noqa: SLF001
            response = await client.messages.parse(
                model=config.model_for("answer"),
                max_tokens=config.max_tokens_for("answer"),
                system=_SYSTEM,
                messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
                output_format=AnswerLLM,
                **kwargs,
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
    deadline: float | None = None,
) -> AnswerResult:
    """Answer one ATS question from profile canned text or a guarded LLM draft.

    Over-length answers are trimmed at a sentence boundary: this path serves copy-paste
    callers (MCP, `POST /api/jobs/{id}/answer`) where a slightly shorter answer beats none.
    `answer_question_async` deliberately rejects instead — see its docstring.
    """
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
    cache_path = _cache_path(
        question, bullets, max_chars=max_chars, resume=resume,
        requirements=requirements, jd_text=jd_text,
    )
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
        deadline=deadline,
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
            deadline=deadline,
        )
        answer_text = retry.answer.strip()
        check = check_claims(resume, bullets, jd_text, answer_text)
        if not check.ok:
            offenders = _offenders_from_check(check)
            warnings.append("Answer discarded after guard failure")
            # Not cached: a guard failure is often one bad draft, and caching it would
            # pin this question to an empty answer until the prompt version changes.
            return AnswerResult(
                answer="",
                offenders=offenders,
                warnings=warnings,
                source="llm",
                model=model_label,
            )

    answer_text, truncate_warnings = _truncate_at_sentence(answer_text, max_chars)
    warnings.extend(truncate_warnings)
    result = AnswerResult(
        answer=answer_text,
        warnings=warnings,
        source="llm",
        model=model_label,
    )
    if use_cache:
        _write_cache(cache_path, result)
    return result


async def answer_question_async(
    question: str, *, resume: MasterResume, bullets: dict[str, str],
    requirements: JobRequirements | None, profile: ApplicantProfile,
    max_chars: int, jd_text: str, deadline: float,
    use_cache: bool = True,
) -> AnswerResult:
    """Guarded Apply answer using cancellable async transport.

    Over-length answers are rejected, not trimmed: this path writes straight into a live
    form field, where a truncated thought or an overflowed ``maxlength`` is worse than
    leaving the field for human review. `answer_question` trims instead.
    """
    # This is one logical stage. Schema repair, provider fallback and the guard retry
    # share its deadline instead of each receiving another minute.
    stage_deadline = min(deadline, time.monotonic() + 60.0)
    if stage_deadline <= time.monotonic():
        raise TimeoutError("Application answer exceeded its deadline")
    model_label = config.backend_for("answer").label()
    canned = _profile_answer(question, profile)
    if canned is not None:
        if len(canned) > max_chars:
            return AnswerResult(
                answer="", warnings=["Saved answer exceeds field limit"],
                source="profile", model=model_label,
            )
        return AnswerResult(answer=canned, source="profile", model=model_label)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _cache_path(
        question, bullets, max_chars=max_chars, resume=resume,
        requirements=requirements, jd_text=jd_text, policy="verified-v1",
    )
    if use_cache and cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        return AnswerResult(
            answer=str(cached.get("answer", "")), offenders=list(cached.get("offenders", [])),
            warnings=list(cached.get("warnings", [])), source=str(cached.get("source", "llm")),
            model=str(cached.get("model", model_label)),
        )
    draft = await _call_model_async(
        question=question, resume=resume, bullets=bullets,
        requirements=requirements, max_chars=max_chars, jd_text=jd_text,
        deadline=stage_deadline,
    )
    answer_text = draft.answer.strip()
    if not answer_text:
        return AnswerResult(answer="", warnings=["No supported answer"], model=model_label)
    check = check_claims(resume, bullets, jd_text, answer_text)
    if not check.ok:
        offenders = _offenders_from_check(check)
        retry = await _call_model_async(
            question=question, resume=resume, bullets=bullets,
            requirements=requirements, max_chars=max_chars, jd_text=jd_text,
            retry_offenders=offenders, deadline=stage_deadline,
        )
        answer_text = retry.answer.strip()
        check = check_claims(resume, bullets, jd_text, answer_text)
        if not answer_text or not check.ok:
            return AnswerResult(
                answer="", offenders=_offenders_from_check(check),
                warnings=["Answer discarded after guard failure"], model=model_label,
            )
    if len(answer_text) > max_chars:
        return AnswerResult(answer="", warnings=["Answer exceeds field limit"], model=model_label)
    result = AnswerResult(answer=answer_text, model=model_label)
    if use_cache:
        _write_cache(cache_path, result)
    return result


#: Bumped when ``_CLASSIFY_SYSTEM`` or the request shape changes; part of each cache key.
_CLASSIFY_PROMPT_VERSION = 1
#: Seconds one classification call may take before the fill carries on without it.
_CLASSIFY_TIMEOUT = 45.0

_CLASSIFY_SYSTEM = """\
You sort job-application questions. For each numbered question, reply with the one key
from the list whose meaning the question asks about, or "none" when no key fits exactly.
Reply with keys only: never answer a question, and never make up a key.
"""


class ClassifiedLLM(BaseModel):
    """Schema-validated model output: one key (or "none") per question, in order."""

    keys: list[str] = Field(default_factory=list)


def _classify_cache_path(question: questions.Question) -> Path:
    payload = "\n".join(
        [
            str(_CLASSIFY_PROMPT_VERSION),
            config.fingerprint("answer"),
            *sorted(questions.MODEL_KEYS),
            normalize_question(question.text),
            *question.options,
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return config.CACHE_DIR / f"{digest}.question-key.json"


def classify_questions(asked: list[questions.Question]) -> list[str | None]:
    """Which of `questions.MODEL_KEYS` each question asks about, None for none of them.

    The fallback for choice questions no rule covers: one ``answer``-purpose call for all
    of them, each result cached by the question's wording and options so the same
    question keys the same way every time. The model sees question text and options only
    and returns keys only; the answer is computed from the profile (`questions.answers`).
    A failed call keys nothing, and the questions are left for review.
    """
    keys: list[str | None] = [None] * len(asked)
    pending: list[int] = []
    for index, question in enumerate(asked):
        path = _classify_cache_path(question)
        if path.is_file():
            cached = json.loads(path.read_text(encoding="utf-8")).get("key")
            keys[index] = cached if cached in questions.MODEL_KEYS else None
        else:
            pending.append(index)
    if not pending:
        return keys
    listing = "\n".join(f"- {key}: {meaning}" for key, meaning in questions.MODEL_KEYS.items())
    numbered = "\n".join(
        f"{number}. {asked[index].text.strip()}"
        + (f" (options: {' | '.join(asked[index].options)})" if asked[index].options else "")
        for number, index in enumerate(pending, start=1)
    )
    try:
        client = llm.client_for("answer")
        if hasattr(client, "timeout"):
            client.timeout = min(float(client.timeout), _CLASSIFY_TIMEOUT)
        elif hasattr(client, "with_options"):
            client = client.with_options(timeout=_CLASSIFY_TIMEOUT)
        response = client.messages.parse(
            model=config.model_for("answer"),
            max_tokens=config.max_tokens_for("answer"),
            system=_CLASSIFY_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"<keys>\n{listing}\n</keys>\n\n<questions>\n{numbered}\n</questions>",
            }],
            output_format=ClassifiedLLM,
        )
        replies = list(response.parsed_output.keys)
    except Exception:  # noqa: BLE001 - a classifier outage must never stop a fill
        return keys
    if len(replies) != len(pending):
        return keys  # misaligned: no reply can be trusted to name its question
    for index, reply in zip(pending, replies, strict=True):
        key = reply.strip() if reply.strip() in questions.MODEL_KEYS else None
        keys[index] = key
        _classify_cache_path(asked[index]).write_text(
            json.dumps({"key": key or "none"}) + "\n", encoding="utf-8"
        )
    return keys
