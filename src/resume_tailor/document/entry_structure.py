"""Finding section headings and splitting a section body into entries by paragraph
fingerprint."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from . import analysis_types, docx_text


def _classify_heading(text: str) -> tuple[str | None, float, str]:
    """Map heading text to a canonical section key with a confidence score."""
    stripped = text.strip()
    upper = stripped.upper()
    if upper in analysis_types._HEADING_ALIASES:
        return analysis_types._HEADING_ALIASES[upper], 1.0, upper

    # Short all-caps lines that contain a known keyword.
    if len(stripped) <= 40 and stripped == stripped.upper() and any(c.isalpha() for c in stripped):
        for alias, key in analysis_types._HEADING_ALIASES.items():
            if alias in upper or any(tok in upper for tok in alias.split() if len(tok) > 3):
                # Prefer stronger tokens.
                if key == "experience" and "EXPERIENCE" in upper:
                    return key, 0.85, alias
                if key == "education" and "EDUCATION" in upper:
                    return key, 0.85, alias
                if key == "projects" and "PROJECT" in upper:
                    return key, 0.85, alias
                if key == "skills" and ("SKILL" in upper or "TECHNOLOG" in upper):
                    return key, 0.85, alias

    lower = stripped.lower()
    heuristics = (
        ("experience", ("experience", "employment", "work history"), 0.6),
        ("education", ("education", "academic"), 0.6),
        ("projects", ("project",), 0.55),
        ("skills", ("skills", "technologies", "tech stack"), 0.55),
    )
    for key, needles, conf in heuristics:
        if any(n in lower for n in needles) and len(stripped) <= 48:
            return key, conf, needles[0]
    return None, 0.0, ""

def header_identity_text(doc) -> str:
    """Text of every page header (paragraphs and table cells), one line each.

    Many Word resume templates put the name and contact line in the header part, which
    `iter_document_paragraphs` (body only) never sees.
    """
    lines: list[str] = []
    for section in doc.sections:
        for header in (section.header, section.first_page_header, section.even_page_header):
            if header is None or header.is_linked_to_previous:
                continue
            for paragraph in header.paragraphs:
                lines.append(paragraph.text)
            for table in header.tables:
                for row in table.rows:
                    for cell in row.cells:
                        lines.extend(paragraph.text for paragraph in cell.paragraphs)
    seen: list[str] = []
    for line in lines:
        if line.strip() and line not in seen:
            seen.append(line)
    return "\n".join(seen)

def _is_chrome(text: str) -> bool:
    """Blank, or a decorative rule/underscore line — never an entry header or content.

    Without this, a horizontal-rule paragraph (`"______________"`) reads as an entry
    header to `_split_entries` (non-blank, non-bullet), and whatever field gets mapped to
    "the first header in the section" lands on the rule instead of the real entry below
    it — a live bug in an installed profile, traced back to exactly this.

    Delegates to `docx_text.is_chrome_text` so `template_build` (which clones exactly the
    chrome paragraphs recorded here as spacer donors) cannot drift from this judgement."""
    return docx_text.is_chrome_text(text)

def _looks_like_heading(text: str) -> bool:
    """Structural heading candidate: short, no tab, no colon, no date, mostly uppercase.

    Catches a section title `_classify_heading`'s alias table has no entry for (e.g.
    "OTHER ACTIVITIES", "CERTIFICATIONS") — a user can name a section anything, so no
    fixed alias list can be complete. Deliberately permissive; the caller still requires
    the paragraph to be followed by entry- or bullet-shaped content before treating it as
    a real heading, so an ALL-CAPS one-line achievement is not mistaken for one.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > 48 or "\t" in text or ":" in stripped:
        return False
    if analysis_types._DATE_RE.search(stripped):
        return False
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.8

@dataclass(frozen=True)
class _Fingerprint:
    """Formatting signature of one paragraph, used to cluster paragraphs that were very
    likely authored with the same intent (e.g. "this is a section heading", "this is an
    entry header") independent of what their text says. Read from python-docx's typed
    paragraph/run formatting API, not raw OOXML — every attribute here already has a
    clean typed accessor, and reading it that way is what keeps this resilient to which
    specific XML shape an export happens to use for "bold" or "12pt"."""

    style: str | None
    bold: bool | None
    size: int | None  # EMU, from the first run's explicit font size
    alignment: int | None  # WD_ALIGN_PARAGRAPH value
    left_indent: int | None  # EMU
    space_before: int | None  # EMU
    space_after: int | None  # EMU
    has_tab: bool
    caps_bucket: str

def _caps_bucket(text: str) -> str:
    """Coarse case-shape bucket: "all_caps" (>=80% of letters upper), "title_case"
    (starts upper, not all), or "mixed" (starts lower, or no letters at all)."""
    stripped = text.strip()
    letters = [c for c in stripped if c.isalpha()]
    if not letters:
        return "mixed"
    if sum(1 for c in letters if c.isupper()) / len(letters) >= 0.8:
        return "all_caps"
    if stripped[0].isupper():
        return "title_case"
    return "mixed"

def _fingerprint(p: analysis_types._Para) -> _Fingerprint:
    """Compute `p`'s formatting fingerprint."""
    paragraph = p.paragraph
    style = paragraph.style.name if paragraph.style is not None else None
    pf = paragraph.paragraph_format
    first_run = p.runs[0] if p.runs else None
    first_size = first_run.font.size if first_run is not None else None
    return _Fingerprint(
        style=style,
        bold=first_run.bold if first_run is not None else None,
        size=first_size.emu if first_size is not None else None,
        alignment=pf.alignment.value if pf.alignment is not None else None,
        left_indent=pf.left_indent.emu if pf.left_indent is not None else None,
        space_before=pf.space_before.emu if pf.space_before is not None else None,
        space_after=pf.space_after.emu if pf.space_after is not None else None,
        has_tab=analysis_types._has_tab_like(p),
        caps_bucket=_caps_bucket(p.text),
    )

def _introduces_content(
    p: analysis_types._Para,
    paras: list[analysis_types._Para],
    heading_fp_classes: frozenset[_Fingerprint] = frozenset(),
) -> bool:
    """True when `p`'s own body — everything after it, up to the next *recognizable*
    heading, or the end of the document — contains at least one Word list bullet or one
    tab-aligned line (the shape of an entry header: "Company | Location\\tDates").

    This is the guard `_looks_like_heading`'s docstring has long claimed the caller
    enforces; nothing actually implemented it until now, which is how an unrecognized
    heading like "PROFESSIONAL SUMMARY" — followed only by a paragraph of prose, never
    a bullet or a tab-aligned entry header — got defaulted to `kind="experience"` by
    the structural fallback below, dragging a real job's header/title prototype onto
    the summary sentence and silently dropping its dates.

    A bulletless, tabless single-line education entry (a real, supported shape — see
    `education_bullets_not_list`) is unaffected: its header line has a tab even when
    its degree line does not, so the section still introduces content.

    "Recognizable" deliberately excludes a merely short/plain/no-tab line: an entry
    header without its own trailing date on the same line — a company name on its own
    line, title on the next — is *also* short and plain, and stopping the scan there
    made a real section heading with a two-line first entry (e.g. "WORK EXPERIENCE"
    followed by "AMAZON WEB SERVICES" then a tab+date title line) register as
    introducing nothing, since the scan gave up one line too early. Only two things
    count as an unambiguous next heading: an alias/keyword text match
    (`_classify_heading`), or — once the caller has a corroborating fingerprint class in
    hand (see `_heading_classes`) — membership in that class. Both are exactly the
    signals the caller itself already trusts to call something a heading, so this
    cannot recognize a "heading" the rest of the module would not.
    """
    for q in paras:
        if q.id <= p.id or _is_chrome(q.text):
            continue
        stripped = q.text.strip()
        if not stripped:
            continue
        if q.is_bullet or analysis_types._has_tab_like(q):
            return True
        if _classify_heading(stripped)[0] is not None:
            return False  # reached an unambiguous next heading with nothing found
        if heading_fp_classes and _fingerprint(q) in heading_fp_classes:
            return False
    return False

def _heading_classes(paras: list[analysis_types._Para]) -> set[_Fingerprint]:
    """Formatting signatures that recur across the document among short, non-bulleted,
    non-chrome, content-introducing paragraphs — the structural signal that
    corroborates (or fails to corroborate) a text-based heading match.

    A resume's own section headings are typically styled identically to each other and
    to nothing else in the body, so real headings cluster into one shared class of
    several members; a single stray ALL-CAPS line (a product name, an emphatic opener)
    does not repeat and never forms a class of its own.

    Returns the empty set when nothing qualifies (too few candidates, or no fingerprint
    shared by more than one) — callers must degrade to today's text-only behavior in
    that case, not treat an empty result as "nothing is a heading."
    """
    candidates: dict[_Fingerprint, list[analysis_types._Para]] = {}
    for p in paras:
        if p.is_bullet or _is_chrome(p.text):
            continue
        stripped = p.text.strip()
        if not stripped or len(stripped) > 48 or analysis_types._has_tab_like(p) or ":" in stripped:
            continue
        if analysis_types._DATE_RE.search(stripped):
            continue
        if not _introduces_content(p, paras):
            continue
        candidates.setdefault(_fingerprint(p), []).append(p)

    return {fp for fp, members in candidates.items() if len(members) >= 2}

def _immediately_follows_entry_header(
    p: analysis_types._Para, paras: list[analysis_types._Para]
) -> bool:
    """True when the nearest preceding non-chrome paragraph has a tab and is not
    itself a bullet — the shape of an entry header ("Company | Location\\tDates").

    A paragraph sitting right after one — a job title line, e.g. "Experience
    Designer" immediately under "Acme Corp | Remote\\tJan 2023 - Present" — is almost
    certainly that entry's title, never a new section heading, regardless of what its
    own text happens to say. This is the case fingerprint corroboration alone cannot
    catch: a title line's formatting can coincidentally land in the same class as the
    document's real headings (both are short, unbulleted, content-introducing text),
    exactly as a real heading styled slightly differently ("SKILLS & Interests" mixing
    case against all-caps siblings) also fails corroboration — confidence and
    formatting alone can't tell the two apart, but position relative to an entry
    header can.
    """
    for q in reversed(paras[: p.id]):
        if _is_chrome(q.text):
            continue
        return analysis_types._has_tab_like(q) and not q.is_bullet
    return False

def _bootstrap_split_entries(paras: list[analysis_types._Para]) -> list[list[analysis_types._Para]]:
    """Group a section body into entries by the bullet-anchored rule alone: a new entry
    starts at any non-bullet paragraph with text, as long as the previous entry (if
    any) has already seen a bullet. Kept as its own function because `_split_entries`
    uses it as a bootstrap pass, then tries to structurally corroborate it — see there.
    """
    entries: list[list[analysis_types._Para]] = []
    for p in paras:
        if _is_chrome(p.text):
            continue
        starts = (not p.is_bullet) and bool(p.text.strip())
        if starts and (not entries or any(x.is_bullet for x in entries[-1])):
            entries.append([p])
        elif entries:
            entries[-1].append(p)
    return entries

def _split_entries(paras: list[analysis_types._Para]) -> list[list[analysis_types._Para]]:
    """Group a section body into entries (an entry-header paragraph, its title/bullets,
    until the next one).

    Two passes. The first (`_bootstrap_split_entries`) is today's contract. The second
    clusters each bootstrap entry's own header paragraph by formatting fingerprint, and
    when a majority share one, re-splits using the *union* of the bootstrap rule
    ("previous entry already saw a bullet") and that class's membership — never the
    fingerprint rule alone. This is what fixes a bulletless pseudo-entry (a stray
    heading-shaped line the classifier could not name, or a genuinely bulletless
    single-line entry) swallowing the real entry after it: the bullet-anchored rule
    alone cannot tell "this entry just doesn't have a bullet yet" from "this line was
    never a real entry start", but a formatting match against the *other* entries' own
    headers can, and critically can find a boundary the bootstrap pass never proposed in
    the first place since it scans every paragraph in the section, not just the ones
    bootstrap already treated as entry starts.

    Union, not replacement: an entry whose header simply lacks the dominant format (an
    otherwise-ordinary entry that happens to have no tab-aligned date, e.g. an
    unfinished/current role) is *already* a correct bootstrap boundary — a
    fingerprint-only re-split would incorrectly re-merge it into its predecessor for no
    reason but the format mismatch, trading one entry-splitting bug for another.
    """
    bootstrap = _bootstrap_split_entries(paras)
    if len(bootstrap) < 2:
        return bootstrap

    header_fps = [_fingerprint(entry[0]) for entry in bootstrap]
    dominant_fp, dominant_count = Counter(header_fps).most_common(1)[0]
    if dominant_count <= len(header_fps) / 2:
        return bootstrap  # no majority formatting agreement; keep the bootstrap split

    entries: list[list[analysis_types._Para]] = []
    for p in paras:
        if _is_chrome(p.text):
            continue
        plain = (not p.is_bullet) and bool(p.text.strip())
        bootstrap_starts = plain and (not entries or any(x.is_bullet for x in entries[-1]))
        fingerprint_starts = plain and _fingerprint(p) == dominant_fp
        if bootstrap_starts or fingerprint_starts:
            entries.append([p])
        elif entries:
            entries[-1].append(p)
        # else: paragraph before the first matching header is dropped, matching
        # `_bootstrap_split_entries`'s own behavior of ignoring anything before the
        # first detected entry start.
    return entries
