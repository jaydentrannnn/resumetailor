"""Reading an entry header (title, org, dates, location) from text, runs or table cells,
and reconciling it across the section's entries."""

from __future__ import annotations

import re
from collections import Counter

from . import analysis_types
from .template_profile import (
    CharSpan,
    HeaderFieldMapping,
    OptionalSpan,
)


def _span(paragraph_id: int, start: int, end: int) -> CharSpan:
    """Build a CharSpan."""
    return CharSpan(paragraph_id=paragraph_id, start=start, end=end)

def _header_fields_from_text(
    para: analysis_types._Para,
    *,
    primary: str,
    secondary: str | None,
    date_field: str,
    exclude_after: int | None = None,
) -> tuple[HeaderFieldMapping, list[analysis_types.FieldCandidate]]:
    """Heuristic split of a header line into primary | secondary \\t dates.

    `exclude_after` clips the primary/secondary search region to `text[:exclude_after]`,
    used to keep a trailing hyperlink label (mapped separately as `link`) out of the
    `secondary`/`tech` span — without it, a header with a link but no tech
    (``"Name | Github\\tdate"``) reads the link's own label as `secondary`, giving `tech`
    and `link` the same span and making the build reject them as overlapping.
    """
    text = para.text
    candidates: list[analysis_types.FieldCandidate] = []
    fields: dict[str, OptionalSpan] = {}

    tab_idx = text.find("\t")
    before = text if tab_idx < 0 else text[:tab_idx]
    after = "" if tab_idx < 0 else text[tab_idx + 1 :]

    date_alignment = "tab" if tab_idx >= 0 else "inline"
    if after.strip() or (tab_idx < 0 and analysis_types._DATE_RE.search(text)):
        if after.strip():
            start = tab_idx + 1
            # Skip leading whitespace after tab.
            while start < len(text) and text[start].isspace():
                start += 1
            end = len(text.rstrip())
            fields[date_field] = OptionalSpan(
                present=True, span=_span(para.id, start, end)
            )
            candidates.append(
                analysis_types.FieldCandidate(
                    field=date_field,
                    span=fields[date_field].span,  # type: ignore[arg-type]
                    confidence=0.9 if tab_idx >= 0 else 0.6,
                    preview=text[start:end],
                )
            )
        else:
            m = analysis_types._DATE_RE.search(text)
            if m:
                fields[date_field] = OptionalSpan(
                    present=True, span=_span(para.id, m.start(), m.end())
                )
                date_alignment = "inline"
                candidates.append(
                    analysis_types.FieldCandidate(
                        field=date_field,
                        span=fields[date_field].span,  # type: ignore[arg-type]
                        confidence=0.7,
                        preview=m.group(0),
                    )
                )
                before = text[: m.start()].rstrip(" |·/–—")
            else:
                fields[date_field] = OptionalSpan(present=False)
    else:
        fields[date_field] = OptionalSpan(present=False)

    if exclude_after is not None and exclude_after < len(before):
        before = before[:exclude_after]

    # Split before-tab on a pipe-like separator. Only the first two segments become
    # primary/secondary — further segments (e.g. " | Github" on project headers) are
    # left for project-specific link detection so they do not inflate `tech` and then
    # overlap when the link span is merged in.
    sep = None
    for candidate in (" | ", "|", " — ", " – ", " - "):
        if candidate in before:
            sep = candidate
            break
    if sep and secondary:
        parts = [p.strip() for p in before.split(sep) if p.strip()]
        left_s = parts[0] if parts else ""
        right_s = parts[1] if len(parts) > 1 else ""
        if not left_s:
            fields[primary] = OptionalSpan(present=False)
            fields[secondary] = OptionalSpan(present=False)
        else:
            # Map back to offsets in `text` (before is a prefix of text).
            left_start = text.find(left_s)
            if left_start < 0:
                fields[primary] = OptionalSpan(present=False)
                fields[secondary] = OptionalSpan(present=False)
            else:
                fields[primary] = OptionalSpan(
                    present=True,
                    span=_span(para.id, left_start, left_start + len(left_s)),
                )
                candidates.append(
                    analysis_types.FieldCandidate(
                        field=primary,
                        span=fields[primary].span,  # type: ignore[arg-type]
                        confidence=0.85,
                        preview=left_s,
                    )
                )
                if right_s:
                    # Search after the primary so a repeated token cannot point left.
                    right_start = text.find(right_s, left_start + len(left_s))
                    if right_start < 0:
                        fields[secondary] = OptionalSpan(present=False)
                    else:
                        fields[secondary] = OptionalSpan(
                            present=True,
                            span=_span(
                                para.id, right_start, right_start + len(right_s)
                            ),
                        )
                        candidates.append(
                            analysis_types.FieldCandidate(
                                field=secondary,
                                span=fields[secondary].span,  # type: ignore[arg-type]
                                confidence=0.8,
                                preview=right_s,
                            )
                        )
                else:
                    fields[secondary] = OptionalSpan(present=False)
    else:
        primary_text = before.strip()
        if primary_text:
            start = text.find(primary_text)
            fields[primary] = OptionalSpan(
                present=True, span=_span(para.id, start, start + len(primary_text))
            )
            candidates.append(
                analysis_types.FieldCandidate(
                    field=primary,
                    span=fields[primary].span,  # type: ignore[arg-type]
                    confidence=0.7,
                    preview=primary_text,
                )
            )
        else:
            fields[primary] = OptionalSpan(present=False)
        if secondary:
            fields[secondary] = OptionalSpan(present=False)

    header = HeaderFieldMapping(
        header_paragraph_id=para.id,
        fields=fields,
        date_alignment=date_alignment,  # type: ignore[arg-type]
    )
    return header, candidates

_BARE_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

def _entry_main_paragraphs(entry: list[analysis_types._Para]) -> list[analysis_types._Para]:
    """`entry` with its header's cross-cell siblings (location/dates in a table
    layout's other cell, sharing the header's row) removed — every other paragraph
    (title lines, bullets, later rows) is untouched.

    Without this, `titles`/`detail_paras`-style scans over `entry[1:]` pick up a table
    layout's location/date cell as if it were a job title or an education detail line,
    since depth-first flattening puts the whole row — both cells — before the next
    row's bullets.
    """
    head = entry[0]
    loc = head.location
    if loc is None:
        return entry
    return [
        p
        for p in entry
        if not (
            p.location is not None and p.location.row == loc.row and p.location.cell != loc.cell
        )
    ]

def _header_fields_across_cells(
    entry: list[analysis_types._Para], *, primary: str, secondary: str | None, date_field: str
) -> tuple[HeaderFieldMapping, list[analysis_types.FieldCandidate]] | None:
    """Cross-cell counterpart to `_header_fields_from_text`, for a table layout where
    an entry header's company/school/name sits in one cell and its location/dates sit
    in the row's other cell (`Company | Location\\tDates` expressed as two cells
    instead of text either side of a tab).

    Returns `None` when the header paragraph isn't in a table row with a second
    populated cell — the caller falls back to the ordinary single-paragraph split.

    Location vs. dates in the side cell is resolved positionally, corroborated by
    `_DATE_RE`, never by `_DATE_RE` alone: it requires a month name or a year range, so
    a degree line's "Class of 2027" matches nothing, and a regex-first rule would wrongly
    leave it unmapped. With two side paragraphs, the second is dates (mirroring
    `Company | Location\\tDates`'s left-to-right order); with one, it's dates only when
    it looks date-shaped, else location — the two swap if `_DATE_RE` disagrees with
    that call for either paragraph.
    """
    head = entry[0]
    loc = head.location
    if loc is None or loc.row_content_cells < 2:
        return None

    main = [
        p
        for p in entry
        if p.location is not None and p.location.row == loc.row and p.location.cell == loc.cell
    ]
    side = [
        p
        for p in entry
        if p.location is not None
        and p.location.row == loc.row
        and p.location.cell != loc.cell
        and p.text.strip()
    ]
    if not main or not side:
        return None

    def _looks_like_date(text: str) -> bool:
        return bool(analysis_types._DATE_RE.search(text)) or bool(_BARE_YEAR_RE.search(text))

    secondary_para: analysis_types._Para | None
    date_para: analysis_types._Para | None
    if len(side) >= 2:
        secondary_para, date_para = side[0], side[-1]
    else:
        p0 = side[0]
        if _looks_like_date(p0.text):
            secondary_para, date_para = None, p0
        else:
            secondary_para, date_para = p0, None

    if (
        secondary_para is not None
        and date_para is not None
        and _looks_like_date(secondary_para.text)
        and not _looks_like_date(date_para.text)
    ):
        secondary_para, date_para = date_para, secondary_para

    fields: dict[str, OptionalSpan] = {}
    candidates: list[analysis_types.FieldCandidate] = []

    def _field_span(name: str, para: analysis_types._Para, confidence: float) -> None:
        text = para.text
        stripped = text.strip()
        start = text.find(stripped)
        span = _span(para.id, start, start + len(stripped))
        fields[name] = OptionalSpan(present=True, span=span)
        candidates.append(
            analysis_types.FieldCandidate(
                field=name, span=span, confidence=confidence, preview=stripped
            )
        )

    _field_span(primary, main[0], 0.85)
    if secondary and secondary_para is not None:
        _field_span(secondary, secondary_para, 0.8)
    elif secondary:
        fields[secondary] = OptionalSpan(present=False)
    if date_para is not None:
        _field_span(date_field, date_para, 0.9)
    else:
        fields[date_field] = OptionalSpan(present=False)

    header = HeaderFieldMapping(
        header_paragraph_id=main[0].id,
        fields=fields,
        date_alignment="separate_paragraph",
        date_paragraph_id=date_para.id if date_para is not None else None,
    )
    return header, candidates

def _entry_header_fields(
    entry: list[analysis_types._Para],
    *,
    primary: str,
    secondary: str | None,
    date_field: str,
    exclude_after: int | None = None,
) -> tuple[HeaderFieldMapping, list[analysis_types.FieldCandidate]]:
    """Header fields for one entry, cross-cell aware.

    Delegates to `_header_fields_from_text` (one paragraph, split on a tab or a
    pipe-like separator) unless the entry's header paragraph sits in a table row with a
    second populated cell, in which case `_header_fields_across_cells` reads
    location/dates out of that other cell instead. Keyed on "the row has a second
    physical cell", never on a fixed `gridSpan` — a document's WORK EXPERIENCE rows can
    be a 3+1 split while its LEADERSHIP rows are 2+2, and both are the same shape
    logically.
    """
    cross = _header_fields_across_cells(
        entry, primary=primary, secondary=secondary, date_field=date_field
    )
    if cross is not None:
        return cross
    return _header_fields_from_text(
        entry[0],
        primary=primary,
        secondary=secondary,
        date_field=date_field,
        exclude_after=exclude_after,
    )

def _reconcile_header_fields(
    entries: list[list[analysis_types._Para]],
    *,
    primary: str,
    secondary: str | None,
    date_field: str,
) -> tuple[list[list[analysis_types._Para]], dict[str, bool], dict[str, float]]:
    """Run `_header_fields_from_text` on *every* entry's own header line, not just the
    one prototype the caller will eventually pick, and determine per-field whether a
    majority of entries actually carry it.

    A single-prototype's field detection is only as reliable as whichever entry
    happens to score highest for "looks like the best header" (`_exp_score` and
    friends) — if that one entry's dates genuinely are not present (a header formatted
    slightly differently than the rest, a role with no end date typed), the mapping
    would lose the field for *every* rendered entry, even though the rest of the
    section clearly has it.

    Returns `(candidate_entries, field_majority, field_confidence)`:
    - `candidate_entries`: the subset of `entries` whose own header's field-presence
      signature (which of primary/secondary/date_field it found) matches the modal
      signature across the section. The caller picks its prototype from *this* list
      (via `_exp_score` or similar), not from `entries` at large, so an outlier entry
      can never become the prototype merely by scoring highest on some unrelated
      dimension (more runs, a title line) while disagreeing with the section on which
      fields even exist.
    - `field_majority`: per field name, whether more than half of all entries carry it
      — what a caller uses to decide whether a field should be considered reliably
      present for the section as a whole, independent of what the eventually-chosen
      prototype's own header spans say.
    - `field_confidence`: per field name, the raw presence rate (0.0-1.0) across all
      entries — becomes `FieldCandidate.confidence`, which today is a fixed constant
      regardless of how many entries actually agree a field is there.

    Falls back to treating every entry as a candidate, with 100% confidence on
    whichever fields the single entry has, when there is only one entry — nothing to
    reconcile against.
    """
    if not entries:
        return [], {}, {}
    if len(entries) == 1:
        header, _ = _entry_header_fields(
            entries[0], primary=primary, secondary=secondary, date_field=date_field
        )
        names = [primary] + ([secondary] if secondary else []) + [date_field]
        presence = {
            n: header.fields.get(n, OptionalSpan(present=False)).present for n in names
        }
        return list(entries), presence, {n: 1.0 if presence[n] else 0.0 for n in names}

    per_entry: list[tuple[list[analysis_types._Para], HeaderFieldMapping]] = []
    for entry in entries:
        header, _ = _entry_header_fields(
            entry, primary=primary, secondary=secondary, date_field=date_field
        )
        per_entry.append((entry, header))

    field_names = [primary] + ([secondary] if secondary else []) + [date_field]

    def _present(header: HeaderFieldMapping, name: str) -> bool:
        return header.fields.get(name, OptionalSpan(present=False)).present

    field_confidence = {
        name: sum(1 for _, h in per_entry if _present(h, name)) / len(per_entry)
        for name in field_names
    }
    field_majority = {name: field_confidence[name] > 0.5 for name in field_names}

    def _signature(header: HeaderFieldMapping) -> tuple[bool, ...]:
        return tuple(_present(header, n) for n in field_names)

    modal_signature = Counter(_signature(h) for _, h in per_entry).most_common(1)[0][0]
    candidate_entries = [entry for entry, h in per_entry if _signature(h) == modal_signature]

    return candidate_entries, field_majority, field_confidence

def _prototype_consistency_issue(
    proto: list[analysis_types._Para], para_ids: dict[str, int | None], label: str
) -> analysis_types.Issue | None:
    """Blocking issue when any of `para_ids` (e.g. header/title/bullet paragraph ids)
    falls outside `proto`'s own paragraph span.

    A prototype whose pieces come from different entries — most often via a "fall back
    to any bullet in the section" escape hatch, reached when the chosen entry itself
    has none — produces a template whose built loop body mixes fragments from
    unrelated entries: a company from one job, a bullet from another. Never silently
    accepted, the same "never silently truncate" rule CLAUDE.md states for the fit
    loop, applied here to "never silently splice."
    """
    proto_ids = {p.id for p in proto}
    offenders = {
        name: pid for name, pid in para_ids.items() if pid is not None and pid not in proto_ids
    }
    if not offenders:
        return None
    detail = ", ".join(f"{name} is paragraph {pid}" for name, pid in offenders.items())
    return analysis_types.Issue(
        code="prototype_spans_multiple_entries",
        message=(
            f"{label} prototype fields come from different entries: {detail} "
            f"(prototype entry spans paragraphs {sorted(proto_ids)})."
        ),
        blocking=True,
    )
