"""Claim checks for after-send drafts, supported only by the sent text and typed facts.

The current master resume is consulted only for a removal warning, never as evidence.
Reuse the existing term and numeric checks without its live-resume lookup or JD sources.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..content.data import Bullet, MasterResume
from . import coverletter_style
from .coverletter import ClaimCheck, _claim_fabrication_offenders


def check_claims(
    bullets: dict[str, str], text: str, *, extra_sources: Sequence[str] = ()
) -> ClaimCheck:
    """Check every sentence against frozen text, independent of current ids and tags."""
    source = [Bullet(id=bid, text=body) for bid, body in bullets.items() if body.strip()]
    extra = " ".join(part.strip() for part in extra_sources if part and part.strip())
    if extra:
        source.append(Bullet(id="__sent_typed_facts__", text=extra))
    terms = _claim_fabrication_offenders([text], source, first_person_only=False)
    numbers = coverletter_style._numbers_not_in_source(text, source, "")
    return ClaimCheck(
        ok=not terms and not numbers,
        unsupported_terms=terms,
        unsupported_numbers=numbers,
    )


def missing_bullet_warnings(resume: MasterResume, bullets: dict[str, str]) -> list[str]:
    missing = bullets.keys() - {bullet.id for bullet in resume.all_bullets()}
    if not missing:
        return []
    subject = "1 sent bullet is" if len(missing) == 1 else f"{len(missing)} sent bullets are"
    return [
        f"{subject} no longer in your master resume. Check the sent text in case it was "
        "removed to correct a fact."
    ]
