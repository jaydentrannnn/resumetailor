"""Spacing, the name line, and the contact line: separator, field order, fields present."""

from __future__ import annotations

import re

from . import analysis_types, entry_structure
from .template_profile import (
    ContactField,
    ContactSlot,
    SpacingProfile,
)


def _representative_run(runs: list[list[int]], applicable: int) -> list[int]:
    """Pick the run to reproduce from every run observed at one slot.

    Two filters, in order. A slot must have been observed in a **majority** of the places
    it could apply, so one stray blank does not add a spacer everywhere the mapping is
    later applied. Among the surviving runs the **modal length** wins, so a section that
    happens to carry three blank paragraphs where every other section carries one does
    not inflate the gap document-wide; ties go to the shorter run, since over-spacing
    costs page height and this only ever needs to look consistent.
    """
    if not runs or not applicable or len(runs) <= applicable / 2:
        return []
    lengths = [len(r) for r in runs]
    best = min(set(lengths), key=lambda n: (-lengths.count(n), n))
    return next(r for r in runs if len(r) == best)

def _chrome_runs(
    body: list[analysis_types._Para],
) -> list[
    tuple[analysis_types._Para | None, list[analysis_types._Para], analysis_types._Para | None]
]:
    """Split `body` into maximal runs of chrome paragraphs, each with the non-chrome
    paragraph immediately before and after it (`None` at a boundary of the list)."""
    runs: list[
        tuple[analysis_types._Para | None, list[analysis_types._Para], analysis_types._Para | None]
    ] = []
    i = 0
    while i < len(body):
        if not entry_structure._is_chrome(body[i].text):
            i += 1
            continue
        start = i
        while i < len(body) and entry_structure._is_chrome(body[i].text):
            i += 1
        before = body[start - 1] if start > 0 else None
        after = body[i] if i < len(body) else None
        runs.append((before, body[start:i], after))
    return runs

def _detect_spacing(
    paras: list[analysis_types._Para], section_candidates: list[analysis_types.SectionCandidate]
) -> SpacingProfile:
    """Detect the chrome-paragraph runs a document reproduces consistently around
    sections: before each heading, right after each heading, and between entries.

    Runs, not single paragraphs, because real exports put several chrome paragraphs at
    one slot — a horizontal rule plus a blank under every heading is the common case, and
    two consecutive blanks between entries is not rare. Detecting only a single blank
    both dropped the rule (it is not blank, so it matched nothing and was deleted with
    the rest of the body) and missed the two-blank gap entirely (each blank's neighbour
    was the other blank rather than the bullet/header pair the boundary test looked for).
    """
    if not section_candidates:
        return SpacingProfile()

    before_runs: list[list[int]] = []
    after_runs: list[list[int]] = []
    between_runs: list[list[int]] = []
    between_applicable = 0

    for sec in section_candidates:
        # Walk back from the heading while the paragraph above is chrome.
        run: list[int] = []
        pid = sec.heading_paragraph_id - 1
        while pid >= 0 and entry_structure._is_chrome(paras[pid].text):
            run.insert(0, pid)
            pid -= 1
        if run:
            before_runs.append(run)

        body = [p for p in paras if sec.body_start <= p.id < sec.body_end]
        runs = _chrome_runs(body)

        # The after-heading run is the one that opens the body (nothing non-chrome
        # before it inside this section).
        for before, chrome, _after in runs:
            if before is None:
                after_runs.append([p.id for p in chrome])
            break

        if sec.key in ("experience", "projects", "education") and sec.entry_count >= 2:
            between_applicable += 1
            for before, chrome, after in runs:
                # An entry boundary: the run closes one entry's bullets and opens the
                # next entry's header. A run with no `after` is the trailing gap before
                # the *next section's* heading (counted as `before_heading` instead), and
                # a run whose predecessor is not a bullet sits inside an entry (between a
                # company line and its title line, say), not between two entries.
                if (
                    before is not None
                    and before.is_bullet
                    and after is not None
                    and not after.is_bullet
                    and after.text.strip()
                ):
                    between_runs.append([p.id for p in chrome])
                    break

    n = len(section_candidates)
    return SpacingProfile(
        before_heading=_representative_run(before_runs, n),
        after_heading=_representative_run(after_runs, n),
        between_entries=_representative_run(between_runs, between_applicable),
    )

def _contact_separator(text: str) -> str:
    """Pick the most likely contact-line separator from the prototype text."""
    for sep in analysis_types._SEP_CANDIDATES:
        if sep in text:
            return sep
    # Fallback: single bullet character with spaces.
    if "\u2022" in text:
        return " \u2022 "
    if "|" in text:
        return " | "
    return " \u2022 "

def _contact_field_order(text: str) -> list[ContactField]:
    """Infer which contact fields appear and in what order from prototype text."""
    order: list[ContactField] = []
    lower = text.lower()
    # Scan left-to-right by finding earliest match positions.
    finds: list[tuple[int, ContactField]] = []
    if analysis_types._EMAIL_RE.search(text):
        finds.append((analysis_types._EMAIL_RE.search(text).start(), "email"))  # type: ignore[union-attr]
    phone = analysis_types._PHONE_RE.search(text)
    # A bare year range ("2021 - 2025") is digits-space-punctuation-digits just like a
    # phone number, and `_PHONE_RE` alone cannot tell them apart — exclude anything
    # that also looks like a date before trusting it as a phone.
    if phone and not analysis_types._DATE_RE.search(phone.group(0)):
        finds.append((phone.start(), "phone"))
    for label, kind in (("linkedin", "linkedin"), ("github", "github")):
        idx = lower.find(label)
        if idx >= 0:
            finds.append((idx, kind))  # type: ignore[arg-type]
    # Location: leftover leading chunk before first known token, if any.
    if finds:
        first = min(p for p, _ in finds)
        head = text[:first].strip(" \u2022|·/–—\t")
        if (
            head
            and "@" not in head
            and not analysis_types._PHONE_RE.fullmatch(head.replace(" ", ""))
        ):
            finds.append((0, "location"))
    elif text.strip():
        finds.append((0, "location"))

    for _, kind in sorted(finds, key=lambda t: t[0]):
        if kind not in order:
            order.append(kind)
    # Always allow the full set at render time; order is preference for present fields.
    for extra in ("location", "email", "phone", "linkedin", "github"):
        if extra not in order:
            order.append(extra)  # type: ignore[arg-type]
    return order

#: A location paragraph in a table's contact block reads as "City, ST" or "City, ST
#: ZIP" — a comma followed by a two-letter state code. Deliberately narrow: unlike
#: `_contact_field_order`'s single-line fallback (which claims *any* leftover text as
#: `location` because there's nowhere else for it to go), a street-address paragraph
#: ("23320 Arroyo Dr.") must NOT match this, so it can be reported as unmapped rather
#: than guessed at — see `_detect_name_and_contact`.
_LOCATION_LIKE_RE = re.compile(r",\s*[A-Z]{2}\b")

def _contact_fields_present(text: str) -> list[ContactField]:
    """Which contact fields one paragraph's own text plausibly names, in the order
    they appear. Unlike `_contact_field_order`, this never pads out to the full
    five-field set — an empty return means "this paragraph isn't a contact field at
    all" (a street address, say), which is exactly what `_detect_name_and_contact`
    needs to tell a mappable slot from one that must stay a literal.
    """
    finds: list[tuple[int, ContactField]] = []
    email_m = analysis_types._EMAIL_RE.search(text)
    if email_m:
        finds.append((email_m.start(), "email"))
    phone_m = analysis_types._PHONE_RE.search(text)
    if phone_m and not analysis_types._DATE_RE.search(phone_m.group(0)):
        finds.append((phone_m.start(), "phone"))
    lower = text.lower()
    for label, kind in (("linkedin", "linkedin"), ("github", "github")):
        idx = lower.find(label)
        if idx >= 0:
            finds.append((idx, kind))  # type: ignore[arg-type]
    if not finds and _LOCATION_LIKE_RE.search(text):
        finds.append((0, "location"))
    return [f for _, f in sorted(finds, key=lambda t: t[0])]

def _detect_name_and_contact(
    paras: list[analysis_types._Para], first_heading_id: int | None
) -> tuple[int, analysis_types._Para | None, list[ContactSlot], list[analysis_types._Para]]:
    """Name plus the paragraph(s) holding contact info, classified by regex.

    "First two non-empty non-heading paragraphs" (the rule this replaces) is wrong the
    moment a table layout spreads name/address/email/phone across four separate
    paragraphs in four cells: the second paragraph is the street-address line, so a
    joined contact line would be built from an address, and the email/phone would be
    baked into the template as unchanging literals.

    Scans every non-bullet, non-blank paragraph above the first detected section
    heading (or, when none was found at all, falls back to today's exact
    "non-heading-classified content paragraph" scan, so an unrecognizable document
    still fails the same way it always has). Only attempts per-paragraph slot
    classification when the block actually spans a table (at least one candidate
    paragraph carries a `location`) — a paragraph-layout resume with a stray extra
    line before its first heading keeps today's exact behaviour: the first remaining
    paragraph is the whole contact line, verbatim.

    Returns `(name_id, contact_paragraph, slots, unmapped)`. At most one of
    `contact_paragraph` / `slots` is set — `slots` only when the contact block is
    table-shaped *and* splits into two or more recognizable fields; `unmapped` lists
    any table-cell paragraph in the block that named no contact field at all (an
    address line, typically), reported so it's never silently dropped.
    """
    if first_heading_id is not None:
        scope = [p for p in paras if p.id < first_heading_id and p.text.strip() and not p.is_bullet]
    else:
        scope = [
            p
            for p in paras
            if p.text.strip()
            and not p.is_bullet
            and entry_structure._classify_heading(p.text)[0] is None
        ]

    if not scope:
        return 0, None, [], []

    name = scope[0]
    rest = scope[1:]
    if not rest:
        return name.id, None, [], []

    is_table_shaped = any(p.location is not None for p in rest)
    if len(rest) <= 1 or not is_table_shaped:
        return name.id, rest[0], [], []

    slots: list[ContactSlot] = []
    unmapped: list[analysis_types._Para] = []
    for p in rest:
        fields = _contact_fields_present(p.text)
        if fields:
            slots.append(ContactSlot(paragraph_id=p.id, fields=fields))
        else:
            unmapped.append(p)

    if not slots:
        return name.id, rest[0], [], []

    return name.id, None, slots, unmapped
