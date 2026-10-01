"""Bounded model proposals that cannot execute arbitrary browser selectors."""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.forms.field_catalog import classify
from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import FieldObservation
from resume_tailor.infra import llm

_PROMPT_VERSION = 1
_SAFE_FACT_KEYS = {
    "country", "state", "city", "school", "degree_level", "major",
    "phone_device_type", "how_heard",
}
_COMPATIBLE_LABELS = {
    "country": r"\b(country|nation)\b",
    "state": r"\b(state|province|region)\b",
    "city": r"\b(city|town|municipality)\b",
    "school": r"\b(school|university|college|institution)\b",
    "degree_level": r"\b(degree|qualification|education level)\b",
    "major": r"\b(major|discipline|field of study)\b",
    "phone_device_type": r"\b(phone type|device type|mobile or landline)\b",
    "how_heard": r"\b(how did you hear|referral source|source of application)\b",
}


class ControlProposal(BaseModel):
    field_id: str
    fact_id: str
    option_id: str
    action: Literal["select_option"]
    rationale: str = ""


class ControlProposals(BaseModel):
    actions: list[ControlProposal] = Field(default_factory=list)


def safe_facts(fields: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in fields.items() if key in _SAFE_FACT_KEYS and value}


def validate(
    proposal: ControlProposal, observed: dict[str, FieldObservation],
    facts: dict[str, str],
) -> tuple[FieldObservation, str] | None:
    field = observed.get(proposal.field_id)
    if field is None or field.current_value or field.control_kind not in {"native_select", "radio_group"}:
        return None
    if classify(field)[0] == "manual_review":
        return None
    fact = facts.get(proposal.fact_id)
    if not fact:
        return None
    pattern = _COMPATIBLE_LABELS.get(proposal.fact_id)
    if not pattern or not re.search(pattern, f"{field.label} {field.help_text}", re.I):
        return None
    if proposal.fact_id == "country" and "phone" in field.label.casefold():
        return None
    match = match_option(field.options, fact, key=proposal.fact_id)
    if match.status != "matched" or match.option_id != proposal.option_id:
        return None
    return field, fact


async def propose(
    fields: list[FieldObservation], facts: dict[str, str], *,
    deadline: float,
) -> list[tuple[FieldObservation, str]]:
    """Ask once, then accept only observed fields and uniquely matched choices."""
    if not fields or not facts:
        return []
    observed = {field.field_id: field for field in fields}
    import json

    request = {
        "version": _PROMPT_VERSION,
        "fields": [{
            "field_id": item.field_id, "label": item.label,
            "section": item.section_id, "options": [
                {"option_id": option.option_id, "label": option.label}
                for option in item.options if option.enabled and not option.placeholder
            ],
        } for item in fields],
        "facts": [{"fact_id": key, "value": value} for key, value in facts.items()],
    }
    system = (
        "Map observed application choices to explicitly supplied applicant facts. "
        "Return select_option actions only when the option exactly or by declared alias "
        "matches a fact. Never infer or invent facts. Do not answer agreements, "
        "demographics, immigration, sponsorship, or salary questions. "
        "Use only the supplied field_id, fact_id, and option_id."
    )
    remaining = min(60.0, deadline - time.monotonic())
    if remaining <= 0:
        return []
    async with llm.async_client_for("answer") as client:
        import asyncio

        async with asyncio.timeout(remaining):
            kwargs: dict[str, Any] = {"deadline": deadline} if isinstance(client, llm._AsyncOpenAICompatClient) else {}  # noqa: SLF001
            response = await client.messages.parse(
                model=config.model_for("answer"),
                max_tokens=config.max_tokens_for("answer"),
                system=system,
                messages=[{"role": "user", "content": json.dumps(request, ensure_ascii=False)}],
                output_format=ControlProposals,
                **kwargs,
            )
    result = []
    used: set[str] = set()
    for action in response.parsed_output.actions:
        validated = validate(action, observed, facts)
        if validated and action.field_id not in used:
            result.append(validated)
            used.add(action.field_id)
    return result
