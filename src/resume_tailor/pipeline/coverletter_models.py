"""Cover-letter models: the model's raw reply, the drafting angles and the finished letter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from .fabrication import _TOKEN


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
