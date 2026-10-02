"""What approving aliases would rewrite in the master resume (the destructive-write guard)."""

from __future__ import annotations

from . import data, library_models


# --------------------------------------------------------------------------------------
# Alias impact (the destructive-write guard)
# --------------------------------------------------------------------------------------
def alias_impact(
    aliases: dict[str, str], *, resume: data.MasterResume | None = None
) -> list[library_models.AliasImpact]:
    """What approving `aliases` would rewrite in the current master resume, if anything.

    `Bullet._normalise_tags` runs `canonical_tag` on every save (`web/app.py`'s
    `put_master_resume`), so an alias whose *key* is already used as a literal tag would
    be silently collapsed onto its target the next time the resume is saved — this is
    the check that turns that into a visible, confirmable preview instead. An alias with
    no impact here is purely additive: it only widens future JD keyword matching.
    """
    if resume is None:
        try:
            resume = data.load()
        except (FileNotFoundError, ValueError):
            return [
                library_models.AliasImpact(
                    alias=k, canonical=v, affected_tags=[], affected_bullets=[]
                )
                for k, v in aliases.items()
            ]

    out: list[library_models.AliasImpact] = []
    for raw_k, raw_v in aliases.items():
        k = raw_k.strip().lower()
        bullets: list[tuple[str, str]] = []
        for job in resume.experience:
            for bullet in job.bullets:
                if k in bullet.tags:
                    bullets.append((job.company, bullet.id))
        for proj in resume.projects:
            for bullet in proj.bullets:
                if k in bullet.tags:
                    bullets.append((proj.name, bullet.id))
        affected = [k] if (bullets or k in resume.tag_vocabulary) else []
        out.append(
            library_models.AliasImpact(
                alias=raw_k, canonical=raw_v, affected_tags=affected, affected_bullets=bullets
            )
        )
    return out
