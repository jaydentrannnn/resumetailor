"""Convert a confirmed fixed-mode `TemplateProfile` to generic mode.

Generic mode needs three things fixed mode never recorded: the per-heading `sections`
list, the `heading_prototype` every heading clones, and the `spacing` donors. All three
are derived from the stored baseline by the same analyzer helpers an upload uses; the
user's confirmed mappings (`experience`, `education`, …, `contact`, `enabled`) are kept
exactly as they are. No LLM, no document mutation.
"""

from __future__ import annotations

from pathlib import Path

import docx

from . import contact_detect, heading_uniformity, template_analyze, template_tagging
from .template_profile import HeadingPrototype, TemplateProfile

#: Mapping attribute -> the analyzer's section key, in no particular order.
_MAPPED_KINDS = {
    "experience": "experience",
    "education": "education",
    "projects": "projects",
    "skills": "skills",
    "list_section": "list",
}


class ConversionError(RuntimeError):
    """The baseline no longer supports a lossless conversion; the profile stays fixed."""


def _mapped_headings(profile: TemplateProfile) -> dict[int, str]:
    """Heading paragraph id -> analyzer kind, for every enabled mapping the user confirmed."""
    out: dict[int, str] = {}
    for attr, key in _MAPPED_KINDS.items():
        mapping = getattr(profile, attr)
        enabled = getattr(profile.enabled, attr)
        if mapping is not None and enabled:
            out[mapping.heading_paragraph_id] = key
    return out


def to_generic(profile: TemplateProfile, baseline: Path) -> TemplateProfile:
    """Return `profile` converted to `section_mode="generic"`, built from `baseline`.

    Re-analyses the baseline with the confirmed headings forced as overrides, then lifts
    only the generic-only fields. Headings that will change appearance are appended to
    `warnings`. Raises `ConversionError` when the re-analysis disagrees with a confirmed
    heading or the heading donor cannot be tagged.
    """
    if profile.section_mode == "generic":
        return profile
    mapped = _mapped_headings(profile)
    if not mapped:
        raise ConversionError("The template has no enabled section to convert.")

    result = template_analyze.analyze_docx(path=str(baseline), overrides=dict(mapped))
    candidates = result.sections
    found = {c.heading_paragraph_id for c in candidates}
    missing = sorted(set(mapped) - found)
    if missing:
        raise ConversionError(
            f"Re-analysis no longer finds the confirmed heading paragraph(s) {missing}."
        )

    doc = docx.Document(str(baseline))
    paras = template_analyze._load_paras(doc)
    prototype_id = candidates[0].heading_paragraph_id
    if not template_tagging._para_by_id(doc, prototype_id).runs:
        raise ConversionError(f"Heading paragraph {prototype_id} has no text runs to tag.")

    converted = profile.model_copy(deep=True)
    converted.section_mode = "generic"
    converted.sections = template_analyze._detected_sections(candidates)
    converted.heading_prototype = HeadingPrototype(paragraph_id=prototype_id)
    converted.spacing = contact_detect._detect_spacing(paras, candidates)
    converted.paragraph_count = len(paras)
    for message in heading_uniformity.heading_differences(doc, prototype_id, candidates):
        if message not in converted.warnings:
            converted.warnings.append(message)
    return converted
