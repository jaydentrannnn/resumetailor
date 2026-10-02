"""Scoring which detected sections are experience/education/projects/skills, and the
per-section field candidates offered for remapping."""

from __future__ import annotations

from collections.abc import Callable

from . import analysis_types, docx_text, entry_structure, header_fields
from .template_profile import (
    CharSpan,
    OptionalSpan,
)


def _exp_score(entry: list[analysis_types._Para]) -> tuple:
    """Prefer the experience entry with a tab-like header and a title + bullets — the
    same tie-break `_analyze_document`'s installed-prototype selection uses, hoisted to
    module level so `_section_field_candidates` can reuse it per section."""
    header = entry[0]
    bullets = [x for x in entry[1:] if x.is_bullet]
    titles = [x for x in entry[1:] if not x.is_bullet and x.text.strip()]
    return (
        1 if analysis_types._has_tab_like(header) else 0,
        len(header.runs),
        1 if titles else 0,
        len(bullets),
    )

def _edu_score(entry: list[analysis_types._Para]) -> tuple:
    """Prefer the education entry with a tab-like header and more runs — mirrors
    `_exp_score`'s role for education's prototype selection."""
    return (1 if analysis_types._has_tab_like(entry[0]) else 0, len(entry[0].runs))

def _proj_score(entry: list[analysis_types._Para]) -> int:
    """Fewer header runs first — a project header without a tech/date suffix ("Note
    Engine" alone) usually has fewer runs than one with a full "Name | Tech\\tDate"
    line, and the plainer header is the safer prototype to build a template from."""
    return len(entry[0].runs)

def _detect_project_link(
    proto: list[analysis_types._Para],
) -> tuple[OptionalSpan, int | None, analysis_types.FieldCandidate | None]:
    """Hyperlink-based `link` field for a project entry's header line, detected before
    name/tech splitting so `exclude_after` can keep the link label out of `tech`.

    Returns `(link_span, exclude_after, candidate)` — `candidate` is `None` when the
    header paragraph carries no hyperlink before its first tab, in which case the other
    two values are the "absent" defaults.
    """
    header = proto[0]
    if not header.has_hyperlink:
        return OptionalSpan(present=False), None, None
    text = header.text
    tab = text.find("\t")
    limit = len(text) if tab < 0 else tab
    in_region = [
        (s, e) for s, e in docx_text.hyperlink_char_spans(header.paragraph) if e <= limit
    ]
    if not in_region:
        return OptionalSpan(present=False), None, None
    start, end = in_region[-1]
    span = header_fields._span(header.id, start, end)
    return (
        OptionalSpan(present=True, span=span),
        start,
        analysis_types.FieldCandidate(
            field="link", span=span, confidence=0.75, preview=text[start:end]
        ),
    )

def _section_field_candidates(
    paras: list[analysis_types._Para],
    sections: list[analysis_types.SectionCandidate],
    *,
    primary: str,
    secondary: str | None,
    date_field: str,
    pick: Callable[[list[list[analysis_types._Para]]], list[analysis_types._Para]],
    include_title: bool = False,
    include_link: bool = False,
) -> list[analysis_types.FieldCandidate]:
    """Header-field candidates for *every* detected section of one kind, not just the
    kind's single installed prototype.

    The profile installs one prototype per kind (`section_by_key`, pooled across every
    same-kind section via `combined_body`) — correct, and unchanged; that's what the
    caller's own `header`/`*_mapping` construction still uses. But the wizard's
    `AnalyzeReport` shows one field-detection row per *section*, so a kind-wide
    candidate set left every section but the pooled prototype's own looking like nothing
    was detected in it — a document with "WORK EXPERIENCE" and "LEADERSHIP" sections
    showed a false "company/dates — not detected" under LEADERSHIP even though both
    sections' entries have both fields. Confidence here is each section's own presence
    rate across its own entries (via `_reconcile_header_fields` scoped to that section),
    which is what the row claims to be reporting, rather than the kind-wide rate.
    """
    out: list[analysis_types.FieldCandidate] = []
    for sec in sections:
        entries = entry_structure._split_entries(paras[sec.body_start : sec.body_end])
        if not entries:
            continue
        candidate_entries, _field_majority, field_confidence = (
            header_fields._reconcile_header_fields(
                entries, primary=primary, secondary=secondary, date_field=date_field
            )
        )
        proto = pick(candidate_entries)

        exclude_after: int | None = None
        if include_link:
            _link, exclude_after, link_cand = _detect_project_link(proto)
            if link_cand is not None:
                out.append(
                    link_cand.model_copy(
                        update={"section_heading_paragraph_id": sec.heading_paragraph_id}
                    )
                )

        _header, hcands = header_fields._entry_header_fields(
            proto,
            primary=primary,
            secondary=secondary,
            date_field=date_field,
            exclude_after=exclude_after,
        )
        for cand in hcands:
            out.append(
                cand.model_copy(
                    update={
                        "confidence": field_confidence.get(cand.field, cand.confidence),
                        "section_heading_paragraph_id": sec.heading_paragraph_id,
                    }
                )
            )

        if include_title:
            proto_main = header_fields._entry_main_paragraphs(proto)
            titles = [x for x in proto_main[1:] if not x.is_bullet and x.text.strip()]
            if titles:
                stripped = titles[0].text.strip()
                out.append(
                    analysis_types.FieldCandidate(
                        field="title",
                        span=header_fields._span(titles[0].id, 0, len(stripped)),
                        confidence=0.9,
                        preview=stripped[:80],
                        section_heading_paragraph_id=sec.heading_paragraph_id,
                    )
                )
    return out

def _skills_spans(para: analysis_types._Para) -> tuple[CharSpan, CharSpan, str] | None:
    """Split a skills line into label + body on the first colon."""
    text = para.text
    if ":" not in text:
        return None
    idx = text.find(":")
    label = text[:idx].rstrip()
    # Include trailing spaces after colon in the separator; body starts at first non-space.
    sep_end = idx + 1
    while sep_end < len(text) and text[sep_end] == " ":
        sep_end += 1
    body = text[sep_end:]
    if not label or not body.strip():
        return None
    label_start = text.find(label)
    return (
        header_fields._span(para.id, label_start, label_start + len(label)),
        header_fields._span(para.id, sep_end, sep_end + len(body.rstrip())),
        text[idx:sep_end],
    )

def _skills_rows_across_cells(
    body: list[analysis_types._Para],
) -> list[tuple[analysis_types._Para, analysis_types._Para]] | None:
    """Every (label paragraph, value paragraph) pair in a table layout's skills grid,
    row by row — the shared row-pairing logic behind both `_skills_pair_across_cells`
    (one representative pair, for `SkillsMapping`) and `resume_import`'s own need for
    *every* pair (to actually import each group's items, not just learn the format).

    Depth-first flattening yields every label before every value within such a row
    ("Languages:, Skills:, Interests:, <fluent…>, <pivot tables…>, <piano…>"), which
    `_skills_spans` (one paragraph, split on a colon) cannot read at all — its
    "Languages:" has nothing after the colon in the SAME paragraph and returns `None`.

    Pairs cell *i* of the lower-indexed column with cell *i* of the higher-indexed one,
    within each row `body` touches, requiring every row to have exactly two populated
    cells with equal paragraph counts and non-empty label/value text on every pair —
    any row that doesn't fit that shape (this is not a label/value grid after all)
    makes the whole thing return `None` rather than a partial, unreliable pairing.
    """
    rows: dict[tuple[int, int], dict[int, list[analysis_types._Para]]] = {}
    order: list[tuple[int, int]] = []
    for p in body:
        if p.location is None:
            return None
        key = (p.location.table, p.location.row)
        if key not in rows:
            rows[key] = {}
            order.append(key)
        rows[key].setdefault(p.location.cell, []).append(p)

    if not order:
        return None

    pairs: list[tuple[analysis_types._Para, analysis_types._Para]] = []
    for key in order:
        cells = rows[key]
        cell_ids = sorted(cells)
        if len(cell_ids) != 2:
            return None
        left, right = cells[cell_ids[0]], cells[cell_ids[1]]
        if not left or len(left) != len(right):
            return None
        for lp, rp in zip(left, right, strict=True):
            if not lp.text.strip() or not rp.text.strip():
                return None
            pairs.append((lp, rp))
    return pairs

def _skills_pair_across_cells(
    body: list[analysis_types._Para],
) -> tuple[CharSpan, CharSpan, str] | None:
    """Single representative `(label_span, body_span, separator)` pair — same contract
    as `_skills_spans` — since that's all `SkillsMapping` needs: a single prototype
    pair whose formatting the build step clones once per `SkillGroup` at render time.
    See `_skills_rows_across_cells` for the row-pairing this is built on.
    """
    pairs = _skills_rows_across_cells(body)
    if not pairs:
        return None
    lp, rp = pairs[0]
    label = lp.text.strip()
    if label.endswith(":"):
        label = label[:-1].rstrip()
    value = rp.text.strip()
    if not label or not value:
        return None
    label_start = lp.text.find(label)
    body_start = rp.text.find(value)
    return (
        header_fields._span(lp.id, label_start, label_start + len(label)),
        header_fields._span(rp.id, body_start, body_start + len(value)),
        ": ",
    )
