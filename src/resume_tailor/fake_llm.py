"""A deterministic stand-in model for end-to-end tests (``RESUME_TAILOR_FAKE_LLM=1``).

`llm.client_for` returns `FakeClient` instead of a real backend when that variable is
set, so the browser e2e suite (`frontend/e2e/`) can run the whole app with no network,
key or model. It is never on by default, and the server logs a warning at startup when
it is.

Replies are read off the prompt, so they stay guard-clean:
- Rewriting returns every bullet's current text unchanged.
- Scoring gives every bullet 6/10.
- Extraction keeps the known tags whose words appear in the posting.
- Everything else gets the smallest valid answer: empty selections, "keep" verdicts
  and a claim-free cover letter.

Like the real clients, it sees and returns plain strings only.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel

_log = logging.getLogger(__name__)

ENV = "RESUME_TAILOR_FAKE_LLM"


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes", "on")


class _Response:
    def __init__(self, parsed: Any):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


def _bullets(text: str) -> list[tuple[str, str]]:
    """(id, current text) for every ``<bullet id='…'>`` block in a prompt."""
    out = []
    pattern = r"<bullet id=(['\"])(.+?)\1[^>]*>(.*?)(?:</bullet>|(?=<bullet )|$)"
    for match in re.finditer(pattern, text, re.S):
        body = match.group(3)
        inner = re.search(r"<(?:current|source)>(.*?)</(?:current|source)>", body, re.S)
        out.append((match.group(2), (inner.group(1) if inner else body).strip()))
    return out


def _requirements(text: str) -> dict[str, Any]:
    posting = re.search(r"<job_description>(.*?)</job_description>", text, re.S)
    body = (posting.group(1) if posting else text).lower()
    known = re.search(r"<known_tags>(.*?)</known_tags>", text, re.S)
    tags = [t.strip() for t in (known.group(1) if known else "").split(",") if t.strip()]
    named = [
        tag
        for tag in tags
        if re.search(rf"(?<![a-z0-9]){re.escape(tag.lower())}(?![a-z0-9])", body)
    ]
    keywords = [
        {"phrase": tag, "canonical": tag, "importance": "must_have" if i < 3 else "nice_to_have"}
        for i, tag in enumerate(named)
    ]
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return {"title": first_line[:80].title() or "Role", "seniority": "intern", "keywords": keywords}


def _minimal(model: type[BaseModel]) -> BaseModel:
    """The smallest valid instance: defaults kept, required fields empty."""
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if not field.is_required():
            continue
        annotation = field.annotation
        origin = get_origin(annotation)
        if origin in (list, tuple, set):
            values[name] = []
        elif origin is dict:
            values[name] = {}
        elif annotation is bool:
            values[name] = False
        elif annotation in (int, float):
            values[name] = 0
        elif origin is not None and str(origin).endswith("Literal"):
            values[name] = get_args(annotation)[0]
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            values[name] = _minimal(annotation)
        else:
            values[name] = ""
    return model.model_validate(values)


def reply(output_format: type[BaseModel], prompt: str) -> BaseModel:
    """The fake model's answer for one structured request."""
    name = output_format.__name__
    if name == "RewriteResult":
        data: dict[str, Any] = {"bullets": [{"id": i, "text": t} for i, t in _bullets(prompt)]}
    elif name == "ScoreTable":
        data = {
            "scores": [{"id": i, "relevance": 6, "reason": "fake"} for i, _ in _bullets(prompt)]
        }
    elif name == "JobRequirements":
        data = _requirements(prompt)
    elif name == "ReviewLLM":
        data = {"bullets": [{"id": i, "verdict": "keep"} for i, _ in _bullets(prompt)]}
    elif name == "CoverLetterLLM":
        data = {
            "paragraphs": [
                "I am writing to apply for this role.",
                "Thank you for considering my application.",
            ]
        }
    else:
        return _minimal(output_format)
    return output_format.model_validate(data)


class _Messages:
    def parse(self, *, output_format: type[BaseModel], messages: list[dict[str, Any]], **_: Any):
        prompt = "\n\n".join(str(m.get("content", "")) for m in messages)
        return _Response(reply(output_format, prompt))


class _AsyncMessages:
    async def parse(
        self, *, output_format: type[BaseModel], messages: list[dict[str, Any]], **_: Any
    ):
        return _Messages().parse(output_format=output_format, messages=messages)


class FakeClient:
    def __init__(self, purpose: str):
        self.purpose = purpose
        self.messages = _Messages()


class AsyncFakeClient:
    def __init__(self, purpose: str):
        self.purpose = purpose
        self.messages = _AsyncMessages()

    async def __aenter__(self) -> AsyncFakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


def warn_if_enabled() -> None:
    if enabled():
        _log.warning("%s is set: every model call returns canned test replies.", ENV)
