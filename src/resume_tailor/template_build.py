"""Generate a tagged `main_template.docx` from a baseline export.

This module is the ONLY producer of the tagged template (see CLAUDE.md). The CLI
`scripts/build_template.py` is a thin wrapper.

Two modes:
- **Legacy** (no profile): exact all-caps headings and the original Google Docs layout.
- **Profile** (confirmed mapping): tags only mapped character spans so separators and
  tabs from the upload survive; optional sections may be omitted.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from . import config, docx_text
from .docx_text import RunSlice
from .template_profile import CharSpan, OptionalSpan, TemplateProfile

W = qn("w:p")
NOTO_MARKER_FONT = "Noto Sans Symbols"


# --------------------------------------------------------------------------------------
# Low-level XML helpers
# --------------------------------------------------------------------------------------


def make_para(text: str) -> OxmlElement:
    """Build a bare paragraph carrying a `{%p %}` control tag.

    The `p` suffix is load-bearing, not cosmetic. A plain `{% for %}` is substituted
    inline, so the loop body starts mid-paragraph and each iteration re-emits the
    surrounding `<w:p>` fragments — nesting a paragraph inside a paragraph. The result
    is well-formed XML that violates the OOXML schema, and Word refuses to open it with
    a generic "Word experienced an error trying to open the file". `{%p %}` makes
    docxtpl drop the whole enclosing paragraph instead, so loops span entire paragraphs.

    Deliberately style-less: these paragraphs are deleted at render time, so formatting
    on them would be wasted, and inheriting a list style would leave a stray bullet
    behind if a tag were ever mistyped.
    """
    p = OxmlElement("w:p")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    p.append(r)
    return p


def delete(paragraph: Paragraph) -> None:
    paragraph._p.getparent().remove(paragraph._p)


def strip_hyperlinks(paragraph: Paragraph) -> list[str]:
    """Remove `w:hyperlink` wrappers, returning the link texts that were dropped.

    Each project carries its own URL, so a hyperlink baked into the template would point
    every rendered project at the prototype's target. The link is reinstated at render
    time as a docxtpl `RichText`, which supplies the correct per-project URL.
    """
    dropped = []
    for link in paragraph._p.findall(qn("w:hyperlink")):
        dropped.append("".join(t.text or "" for t in link.iter(qn("w:t"))))
        paragraph._p.remove(link)
    return dropped


def has_tab_element(run) -> bool:
    """Whether the run's tab is a `<w:tab/>` element rather than a literal character.

    Word writes tab stops as elements, which `run.text` renders as "\\t". Treating that
    rendered form as if it were real text and rewriting it produced a duplicated tab —
    the element survived the rewrite and a literal tab was added alongside it.
    """
    return run._r.find(qn("w:tab")) is not None


def set_run_text(run, text: str, *, keep_tabs: bool = False) -> None:
    """Replace a run's text, preserving significant whitespace.

    With `keep_tabs`, any `<w:tab/>` elements are left in place and `text` is appended
    after them — use it for the run that holds a header's alignment tab.
    """
    for t in run._r.findall(qn("w:t")):
        run._r.remove(t)
    if not keep_tabs:
        for tab in run._r.findall(qn("w:tab")):
            run._r.remove(tab)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run._r.append(t)


def clone_run_after(run, text: str) -> Run:
    """Duplicate a run (inheriting its formatting) with new text, placed just after it."""
    new_r = copy.deepcopy(run._r)
    run._r.addnext(new_r)
    cloned = Run(new_r, run._parent)
    set_run_text(cloned, text)
    return cloned


def strip_bold(run: Run) -> None:
    """Remove bold from a run's character properties."""
    rPr = run._r.find(qn("w:rPr"))
    if rPr is None:
        return
    for tag in ("w:b", "w:bCs"):
        el = rPr.find(qn(tag))
        if el is not None:
            rPr.remove(el)


def tab_run_index(paragraph: Paragraph) -> int:
    """Return the index of the run holding the header's date-alignment tab."""
    for i, run in enumerate(paragraph.runs):
        if "\t" in run.text or has_tab_element(run):
            return i
    return len(paragraph.runs) - 1


def leading_runs_before_tab(paragraph: Paragraph) -> int:
    """Count runs before the header tab — more runs usually means company/location split."""
    return tab_run_index(paragraph)


def set_num_id(paragraph: Paragraph, num_id: str) -> None:
    """Point a list paragraph at a different numbering definition instance."""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        paragraph._p.insert(0, pPr)
    numPr = pPr.find(qn("w:numPr"))
    if numPr is None:
        numPr = OxmlElement("w:numPr")
        pPr.insert(0, numPr)
    num_id_el = numPr.find(qn("w:numId"))
    if num_id_el is None:
        num_id_el = OxmlElement("w:numId")
        numPr.append(num_id_el)
    num_id_el.set(qn("w:val"), num_id)


def strip_right_indent(paragraph: Paragraph) -> None:
    """Drop a paragraph's right indent — it narrows the column and inflates line count."""
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return
    ind = pPr.find(qn("w:ind"))
    if ind is None:
        return
    if ind.get(qn("w:right")) is not None:
        del ind.attrib[qn("w:right")]


# Word single spacing under lineRule=auto is 240 (240ths of a line).
SINGLE_LINE = "240"


def set_single_spacing(paragraph: Paragraph, *, exact: bool = False) -> None:
    """Force Word single line spacing on a paragraph, preserving before/after gaps.

    `lineRule=auto` is Word's "Single". Bullets also get `exact` so a taller substitute
    bullet font (common under LibreOffice when Noto is missing) cannot inflate the
    auto line box past single — measured wraps were ~15.7pt for 10pt body text.
    """
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        pPr = OxmlElement("w:pPr")
        paragraph._p.insert(0, pPr)
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:line"), SINGLE_LINE)
    # exact locks height in twips (240 = 12pt); auto is Word UI "Single".
    spacing.set(qn("w:lineRule"), "exact" if exact else "auto")


def normalize_single_spacing(doc) -> None:
    """Write single line spacing onto every body paragraph in the document.

    Google Docs exports can leave spacing unset (inherits a looser default) or carry
    Multiple > 1 on some paragraphs. Prototypes alone cannot fix education bullets or
    the name/contact lines, so this runs over the whole document after tagging.
    """
    for paragraph in doc.paragraphs:
        text = (paragraph.text or "").strip()
        # Control-tag paragraphs are dropped at render time; leave them bare.
        if text.startswith("{%p "):
            continue
        set_single_spacing(paragraph, exact=is_bullet(paragraph))


# --------------------------------------------------------------------------------------
# Document structure
# --------------------------------------------------------------------------------------

SECTIONS = ("EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS")


def is_bullet(p: Paragraph) -> bool:
    """A real list paragraph, i.e. one carrying numbering properties."""
    return p._p.find(f".//{qn('w:numPr')}") is not None


def find_sections(doc) -> dict[str, tuple[int, int]]:
    """Map each section heading to the (start, end) paragraph range of its body."""
    heads: dict[str, int] = {}
    for i, p in enumerate(doc.paragraphs):
        text = p.text.strip()
        if text in SECTIONS:
            heads[text] = i

    bounds: dict[str, tuple[int, int]] = {}
    ordered = sorted(heads.items(), key=lambda kv: kv[1])
    for n, (name, idx) in enumerate(ordered):
        end = ordered[n + 1][1] if n + 1 < len(ordered) else len(doc.paragraphs)
        bounds[name] = (idx + 1, end)
    return bounds


def split_entries(paragraphs: list[Paragraph]) -> list[list[Paragraph]]:
    """Group a section's paragraphs into entries.

    An entry starts at a non-bullet paragraph that has actual text; its bullets and any
    sub-heading (a job title) belong to it until the next such paragraph.
    """
    entries: list[list[Paragraph]] = []
    for p in paragraphs:
        starts_entry = not is_bullet(p) and p.text.strip()
        if starts_entry and (not entries or any(is_bullet(x) for x in entries[-1])):
            entries.append([p])
        elif entries:
            entries[-1].append(p)
    return entries


def header_run_count(entry: list[Paragraph]) -> int:
    return len(entry[0].runs)


def vertical_cost(p: Paragraph) -> tuple[int, int]:
    """Approximate how much vertical space a paragraph's formatting costs.

    Returns (line spacing, right indent); lower is more compact. Word's default line
    value is 240 (single), and a right indent narrows the text column, causing earlier
    wrapping and therefore taller blocks.
    """
    line, right = 240, 0
    pPr = p._p.find(qn("w:pPr"))
    if pPr is not None:
        spacing = pPr.find(qn("w:spacing"))
        if spacing is not None and spacing.get(qn("w:line")):
            line = int(float(spacing.get(qn("w:line"))))
        ind = pPr.find(qn("w:ind"))
        if ind is not None and ind.get(qn("w:right")):
            right = int(float(ind.get(qn("w:right"))))
    return line, right


def _num_to_abstract(numbering_root) -> dict[str, str]:
    """Map numbering instance ids to their abstract definition ids."""
    mapping: dict[str, str] = {}
    for num in numbering_root.findall(qn("w:num")):
        nid = num.get(qn("w:numId"))
        abs_el = num.find(qn("w:abstractNumId"))
        if nid is not None and abs_el is not None:
            mapping[nid] = abs_el.get(qn("w:val"), "")
    return mapping


def _abstract_has_noto_marker(numbering_root, abstract_id: str) -> bool:
    """Return whether an abstract numbering definition pins Noto for its lvl0 bullet."""
    for anum in numbering_root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) != abstract_id:
            continue
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            num_fmt = lvl.find(qn("w:numFmt"))
            if num_fmt is None or num_fmt.get(qn("w:val")) != "bullet":
                continue
            rPr = lvl.find(qn("w:rPr"))
            rf = rPr.find(qn("w:rFonts")) if rPr is not None else None
            return rf is not None and rf.get(qn("w:ascii")) == NOTO_MARKER_FONT
    return False


def discover_noto_num_id(doc) -> str | None:
    """Find a list instance id whose lvl0 bullet marker uses Noto Sans Symbols.

    Prefer an id used by education bullets so experience/projects match that section.
    """
    numbering = doc.part.numbering_part
    root = numbering.element
    num_to_abs = _num_to_abstract(root)

    bounds = find_sections(doc)
    candidates: list[str] = []
    if "EDUCATION" in bounds:
        start, end = bounds["EDUCATION"]
        for paragraph in doc.paragraphs[start:end]:
            if not is_bullet(paragraph):
                continue
            pPr = paragraph._p.find(qn("w:pPr"))
            numPr = pPr.find(qn("w:numPr")) if pPr is not None else None
            if numPr is None:
                continue
            num_id_el = numPr.find(qn("w:numId"))
            if num_id_el is None:
                continue
            num_id = num_id_el.get(qn("w:val"))
            if num_id and _abstract_has_noto_marker(root, num_to_abs.get(num_id, "")):
                return num_id
            if num_id:
                candidates.append(num_id)

    for num_id, abstract_id in num_to_abs.items():
        if _abstract_has_noto_marker(root, abstract_id):
            return num_id
    return candidates[0] if candidates else None


def normalize_bullet_numbering(doc) -> None:
    """Pin Noto Sans Symbols on every lvl0 bullet marker in numbering.xml."""
    numbering = doc.part.numbering_part
    root = numbering.element

    ref_rfonts = None
    for anum in root.findall(qn("w:abstractNum")):
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            num_fmt = lvl.find(qn("w:numFmt"))
            if num_fmt is None or num_fmt.get(qn("w:val")) != "bullet":
                continue
            rPr = lvl.find(qn("w:rPr"))
            rf = rPr.find(qn("w:rFonts")) if rPr is not None else None
            if rf is not None and rf.get(qn("w:ascii")) == NOTO_MARKER_FONT:
                ref_rfonts = copy.deepcopy(rf)
                break
        if ref_rfonts is not None:
            break

    if ref_rfonts is None:
        ref_rfonts = OxmlElement("w:rFonts")
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            ref_rfonts.set(qn(f"w:{attr}"), NOTO_MARKER_FONT)

    for anum in root.findall(qn("w:abstractNum")):
        for lvl in anum.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) != "0":
                continue
            num_fmt = lvl.find(qn("w:numFmt"))
            if num_fmt is None or num_fmt.get(qn("w:val")) != "bullet":
                continue
            rPr = lvl.find(qn("w:rPr"))
            if rPr is None:
                rPr = OxmlElement("w:rPr")
                lvl.append(rPr)
            old_rf = rPr.find(qn("w:rFonts"))
            if old_rf is not None:
                rPr.remove(old_rf)
            rPr.insert(0, copy.deepcopy(ref_rfonts))


#: Most fonts (Times New Roman included) draw U+25CF "●" as a near-full-em disc, not
#: the small list dot a dedicated symbol font would give it. Pinning a symbol font at the
#: numbering level does not help: the paragraph mark's own direct rFonts (written by every
#: Google Docs export, on every bullet paragraph) takes precedence over the numbering
#: level's rPr, so the marker always renders in the body font regardless. Shrinking the
#: paragraph mark's own size sidesteps that precedence fight entirely, and works in
#: whatever font actually wins.
BULLET_MARKER_SIZE_RATIO = 0.8 * (2 / 3)  # ~0.53; a further 2/3 pass on top of the first cut
_MIN_MARKER_HALF_POINTS = 8  # 4pt floor so a tiny body font can't shrink the dot to nothing


def shrink_bullet_marker(paragraph: Paragraph) -> None:
    """Scale down the paragraph-mark font size that governs the bullet glyph.

    The paragraph mark's `rPr` (inside `pPr`, not the visible runs) formats only the
    numbering symbol, so this changes the dot's size without touching the bullet's own
    text size.
    """
    pPr = paragraph._p.find(qn("w:pPr"))
    rPr = pPr.find(qn("w:rPr")) if pPr is not None else None
    sz = rPr.find(qn("w:sz")) if rPr is not None else None
    if sz is None or not sz.get(qn("w:val")):
        return
    body_size = int(sz.get(qn("w:val")))
    marker_size = str(max(_MIN_MARKER_HALF_POINTS, round(body_size * BULLET_MARKER_SIZE_RATIO)))
    sz.set(qn("w:val"), marker_size)
    sz_cs = rPr.find(qn("w:szCs"))
    if sz_cs is not None:
        sz_cs.set(qn("w:val"), marker_size)


def retarget_bullet(paragraph: Paragraph, num_id: str | None) -> None:
    """Use the canonical small-marker list id and drop any right-indent inflation."""
    if num_id is not None:
        set_num_id(paragraph, num_id)
    strip_right_indent(paragraph)
    shrink_bullet_marker(paragraph)


def pick_bullet_prototype(entries: list[list[Paragraph]]) -> Paragraph:
    """Choose the most compact bullet in a section to serve as the loop body.

    The source resume is internally inconsistent: some entries' bullets carry a 1.15
    line-spacing override and a right indent, others carry neither. Since one prototype
    drives every rendered bullet, that formatting is necessarily normalised — a bullet
    from any entry may appear where another entry's used to, so per-entry spacing cannot
    survive the loop regardless.

    Given that, normalise *downward*. Picking the loosest prototype silently inflated the
    resume by roughly 15% of a line per bullet and pushed a one-page resume onto two.
    """
    bullets = [p for entry in entries for p in entry if is_bullet(p)]
    if not bullets:
        raise RuntimeError("Section contains no bullet paragraphs to use as a prototype.")
    return min(bullets, key=vertical_cost)


# --------------------------------------------------------------------------------------
# Tagging
# --------------------------------------------------------------------------------------


def tag_header(paragraph: Paragraph, fields: list[str], *, tail_field: str) -> None:
    """Tag a header line of the form `<bold> | <plain>\\t<date>`.

    Runs before the tab receive `fields` in order; the run holding the tab keeps it and
    the text after the tab becomes `tail_field`. Working run-by-run rather than rewriting
    the paragraph is what preserves the bold prefix and the right-aligned tab stop.
    """
    tab_idx = tab_run_index(paragraph)
    runs = paragraph.runs

    # Everything before the tab carries the leading fields.
    lead = runs[:tab_idx]
    for i, run in enumerate(lead):
        set_run_text(run, fields[i] if i < len(fields) else "")

    # More fields than runs: insert plain runs instead of merging into the bold run.
    if len(fields) > len(lead) and lead:
        anchor = lead[-1]
        for field in fields[len(lead) :]:
            plain = clone_run_after(anchor, field)
            strip_bold(plain)
            anchor = plain

    runs = paragraph.runs
    tab_idx = tab_run_index(paragraph)

    # The tab run keeps its tab; the date follows it.
    tab_run = runs[tab_idx]
    element_tab = has_tab_element(tab_run)
    after_tab = tab_run.text.split("\t", 1)[1] if "\t" in tab_run.text else ""

    if after_tab or tab_idx == len(runs) - 1:
        # Tab and date share one run.
        if element_tab:
            set_run_text(tab_run, tail_field, keep_tabs=True)
        else:
            set_run_text(tab_run, "\t" + tail_field)
        for extra in runs[tab_idx + 1 :]:
            paragraph._p.remove(extra._r)
    else:
        # Tab and date are in separate runs; keep that split so the date keeps its own
        # formatting (the tab run is sometimes bold, the date never is).
        if element_tab:
            set_run_text(tab_run, "", keep_tabs=True)
        else:
            set_run_text(tab_run, "\t")
        set_run_text(runs[tab_idx + 1], tail_field)
        for extra in runs[tab_idx + 2 :]:
            paragraph._p.remove(extra._r)


def tag_bullet(paragraph: Paragraph, expr: str) -> None:
    """Collapse a bullet to a single tagged run, keeping its list formatting."""
    runs = paragraph.runs
    set_run_text(runs[0], expr)
    for extra in runs[1:]:
        paragraph._p.remove(extra._r)


def build_loop(
    entry: list[Paragraph],
    anchor: Paragraph,
    *,
    outer: str,
    inner: str,
) -> None:
    """Insert a cloned, tagged entry wrapped in for-loops, before `anchor`."""
    anchor._p.addprevious(make_para(outer))
    for para in entry:
        anchor._p.addprevious(copy.deepcopy(para._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    _ = inner


# --------------------------------------------------------------------------------------
# Section builders
# --------------------------------------------------------------------------------------


def build_name(doc) -> None:
    """Replace the name line with a plain `{{ }}` tag so it comes from the master resume.

    Plain substitution is fine here (unlike the contact line): the name carries no
    hyperlink, so there is no risk of a run nesting inside `<w:t>`.
    """
    if not doc.paragraphs:
        raise RuntimeError("Document is missing the name line (expected paragraph 0).")
    paragraph = doc.paragraphs[0]
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Name line has no runs to tag.")
    # Keep the first run's display-name formatting; collapse everything else into it.
    # Deliberately a distinct top-level key, not `contact.name` — `contact` in the render
    # context is the RichText contact *line* (`{{r contact }}`), which has no attributes.
    set_run_text(runs[0], "{{ name }}")
    for extra in runs[1:]:
        paragraph._p.remove(extra._r)


def build_contact(doc) -> None:
    """Replace the contact line with a single RichText tag.

    The line carries LinkedIn (and optionally GitHub) as real hyperlinks, which differ
    per person and must not be baked into the template. `{{r contact }}` is required —
    a plain `{{ }}` nests the hyperlink's `<w:r>` inside a `<w:t>` and the link vanishes
    on read-back. The baked-in hyperlink is stripped first for the same reason project
    URLs are.
    """
    # Contact is the second body paragraph in the export: name, then location/email/…
    if len(doc.paragraphs) < 2:
        raise RuntimeError("Document is missing the contact line (expected paragraph 1).")
    paragraph = doc.paragraphs[1]
    strip_hyperlinks(paragraph)
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Contact line has no runs to tag.")
    # Keep the first run's Spectral formatting; collapse everything else into it.
    set_run_text(runs[0], "{{r contact }}")
    for extra in runs[1:]:
        paragraph._p.remove(extra._r)


def build_education(doc, entries: list[list[Paragraph]], *, noto_num_id: str | None) -> None:
    """Replace all education entries with one tagged, looped prototype.

    Degree text and detail bullets (coursework joined upstream, plus free-text details)
    come from the master resume so the editor can toggle GPA and edit coursework without
    re-exporting the Google Doc.
    """
    if not entries:
        raise RuntimeError("EDUCATION section has no entries to prototype.")
    # Prefer a header whose school and location already live in separate runs so
    # school stays bold and location stays plain after tagging.
    prototype = max(entries, key=lambda entry: leading_runs_before_tab(entry[0]))
    header, *rest = prototype
    bullets = [p for p in rest if is_bullet(p)]
    if not bullets:
        raise RuntimeError("Education entry is missing a degree/detail bullet.")
    degree = bullets[0]
    # Prefer a different bullet for the detail loop body so tagging one does not
    # overwrite the other when they happen to be the same paragraph object.
    section_bullets = [p for entry in entries for p in entry if is_bullet(p)]
    others = [p for p in section_bullets if p._p is not degree._p]
    detail = min(others, key=vertical_cost) if others else degree
    # When the section has only a degree bullet, clone it so the two tags stay independent.
    if detail._p is degree._p:
        detail_p = copy.deepcopy(degree._p)
        degree._p.addnext(detail_p)
        detail = Paragraph(detail_p, degree._parent)
    retarget_bullet(degree, noto_num_id)
    retarget_bullet(detail, noto_num_id)

    tag_header(
        header,
        ["{{ edu.school }} | ", "{{ edu.location }}"],
        tail_field="{{ edu.dates }}",
    )
    tag_bullet(degree, "{{ edu.degree_line }}")
    tag_bullet(detail, "{{ detail }}")

    anchor = entries[0][0]
    anchor._p.addprevious(make_para("{%p for edu in education %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(degree._p))
    anchor._p.addprevious(make_para("{%p for detail in edu.details %}"))
    anchor._p.addprevious(copy.deepcopy(detail._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    # Drop the temporary clone if we inserted one next to the degree bullet.
    if detail._p.getparent() is not None and detail not in [
        p for entry in entries for p in entry
    ]:
        delete(detail)

    for entry in entries:
        for para in entry:
            delete(para)


def build_experience(doc, entries: list[list[Paragraph]], *, noto_num_id: str | None) -> None:
    """Replace all experience entries with one tagged, looped prototype."""
    # Prefer a header whose company and location already live in separate runs so
    # company stays bold and location stays plain after tagging.
    prototype = max(entries, key=lambda entry: leading_runs_before_tab(entry[0]))

    header, *rest = prototype
    title = next((p for p in rest if not is_bullet(p) and p.text.strip()), None)
    if title is None:
        raise RuntimeError("Experience entry is missing a title paragraph.")
    # The bullet prototype is chosen across the whole section, independently of the
    # header, so spacing is normalised to the tightest variant present.
    bullet = pick_bullet_prototype(entries)
    retarget_bullet(bullet, noto_num_id)

    tag_header(header, ["{{ job.company }} | ", "{{ job.location }}"], tail_field="{{ job.dates }}")
    set_run_text(title.runs[0], "{{ job.title }}")
    for extra in title.runs[1:]:
        title._p.remove(extra._r)
    tag_bullet(bullet, "{{ bullet }}")

    anchor = entries[0][0]
    anchor._p.addprevious(make_para("{%p for job in experience %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(title._p))
    anchor._p.addprevious(make_para("{%p for bullet in job.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    for entry in entries:
        for para in entry:
            delete(para)


def build_projects(doc, entries: list[list[Paragraph]], *, noto_num_id: str | None) -> None:
    """Replace all project entries with one tagged, looped prototype."""
    prototype = min(entries, key=header_run_count)
    header, *rest = prototype
    bullet = pick_bullet_prototype(entries)
    retarget_bullet(bullet, noto_num_id)

    # The per-project URL differs, so the baked-in hyperlink must go; render.py
    # reinstates it as a RichText carrying the right target.
    strip_hyperlinks(header)
    tag_header(
        header,
        # `{{r ... }}` is docxtpl's RichText tag — the inline counterpart of `{%p %}`.
        # A plain `{{ }}` substitutes the value as text, which nests the hyperlink's
        # `<w:r>` inside a `<w:t>`; `w:t` may only contain characters, so the link is
        # silently dropped when the document is read back.
        # Separator before the link lives in the RichText (render.py), not here —
        # otherwise suppressing the link leaves a dangling " | ".
        ["{{ proj.name }} | ", "{{ proj.tech }}", "{{r proj.link }}"],
        tail_field="{{ proj.date }}",
    )
    tag_bullet(bullet, "{{ bullet }}")

    anchor = entries[0][0]
    anchor._p.addprevious(make_para("{%p for proj in projects %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(make_para("{%p for bullet in proj.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    for entry in entries:
        for para in entry:
            delete(para)


def build_skills(doc, paragraphs: list[Paragraph]) -> None:
    """Replace the skills lines with a single looped, tagged line."""
    lines = [p for p in paragraphs if p.text.strip()]
    if not lines:
        return
    # The prototype must keep the export's two-run split: a bold label run and a plain
    # body run. Writing both tags into the label run and dropping the rest discards the
    # plain run's formatting, so the entire rendered line comes out bold.
    prototype = min(
        (p for p in lines if len(p.runs) >= 2), key=lambda p: len(p.runs), default=lines[0]
    )

    # `entries`, not `items`: Jinja resolves `x.items` to the dict's built-in method
    # before the key, and the method's repr gets mangled into bogus XML that Word
    # refuses to open. Avoid any name that collides with a dict attribute.
    #
    # The colon lives in the label run because that is how the export bolds it; the
    # separating space moves to the body run, where `set_run_text` preserves it.
    set_run_text(prototype.runs[0], "{{ group.label }}:")
    if len(prototype.runs) >= 2:
        body = prototype.runs[1]
    else:
        body = clone_run_after(prototype.runs[0], "")
        body.bold = False  # the clone inherits the label's bold
    set_run_text(body, " {{ group.entries }}")
    for extra in list(prototype.runs[2:]):
        prototype._p.remove(extra._r)

    shrink_bullet_marker(prototype)

    anchor = lines[0]
    anchor._p.addprevious(make_para("{%p for group in skills %}"))
    anchor._p.addprevious(copy.deepcopy(prototype._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    for p in lines:
        delete(p)


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# Span-aware tagging (profile mode)
# --------------------------------------------------------------------------------------


_R_TAG = qn("w:r")
_HYPERLINK_TAG = qn("w:hyperlink")

#: Characters that only ever appear as connective punctuation between header fields.
#: Character-class based rather than a fixed separator list, so " • ", " – ", " / " are
#: all recognised the same way " | " is — no per-template special-casing needed.
_SEPARATOR_CHARS = frozenset(" |•·–—/,;-")


@dataclass(frozen=True)
class _Segment:
    """One piece of a rebuilt paragraph, carrying the source offset it inherits from.

    `donor_offset` indexes into the ORIGINAL paragraph text (before any rebuild), and is
    resolved against a `RunSlice` list to decide which run's formatting this piece gets.
    """

    text: str
    donor_offset: int
    kind: Literal["text", "tag", "tab", "break"] = "text"
    field: str = ""


def _is_separator_literal(text: str) -> bool:
    """True when `text` is only whitespace and connective punctuation."""
    return bool(text) and all(ch in _SEPARATOR_CHARS for ch in text)


def _run_shell(donor: RunSlice | None):
    """Build an empty `w:r` carrying a deep copy of `donor`'s `w:rPr`, nothing else.

    Copying only the run properties (not the whole run, unlike `clone_run_after`) means
    cloning many segments from the same donor never duplicates non-text children such as
    a drawing or bookmark.
    """
    r = OxmlElement("w:r")
    if donor is not None:
        rpr = donor.element.find(qn("w:rPr"))
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
    return r


def _append_text(run_el, text: str) -> None:
    """Append a `w:t` to a bare run element, preserving significant whitespace."""
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run_el.append(t)


def _split_literal(
    text: str, start: int, end: int, slices: list[RunSlice]
) -> list[_Segment]:
    """Split a literal gap ``[start:end)`` at source-run boundaries and tab/break chars.

    Splitting at run boundaries is what reproduces a document's own bold/plain split
    across a separator (e.g. a bold ``":"`` immediately followed by a plain space).
    Splitting at every ``\\t``/``\\n``/``\\r`` — regardless of whether it shares a run
    with surrounding text — is what turns a literal tab into a real ``<w:tab/>`` element
    instead of a character inside a `w:t`, which is what keeps a date right-aligned.
    """
    if start >= end:
        return []
    cut_points = {start, end}
    for s in slices:
        if start < s.start < end:
            cut_points.add(s.start)
        if start < s.end < end:
            cut_points.add(s.end)
    for i in range(start, end):
        if text[i] in "\t\n\r":
            cut_points.add(i)
            cut_points.add(i + 1)
    points = sorted(p for p in cut_points if start <= p <= end)

    segments: list[_Segment] = []
    for a, b in zip(points, points[1:]):
        if a == b:
            continue
        piece = text[a:b]
        if piece == "\t":
            segments.append(_Segment(text="", donor_offset=a, kind="tab"))
        elif piece in ("\n", "\r"):
            segments.append(_Segment(text="", donor_offset=a, kind="break"))
        else:
            segments.append(_Segment(text=piece, donor_offset=a, kind="text"))
    return segments


def build_segments(
    text: str,
    slices: list[RunSlice],
    items: list[tuple[int, int, str, str]],
    *,
    drop_hyperlink_literals: bool = True,
    render_owned_separator_before: frozenset[str] = frozenset(),
) -> list["_Segment"]:
    """Turn ordered field spans and the literal text between them into donor-tagged pieces.

    `items` is a list of ``(start, end, tag, field_name)``. Fails loudly rather than
    truncating: raises when a span exceeds the paragraph, contains a tab or line break,
    or overlaps another mapped span (naming both fields).

    `drop_hyperlink_literals` removes any literal piece whose source run sits inside a
    baked-in `w:hyperlink` — a per-project label like "Github" must never survive into
    the shared template. `render_owned_separator_before` names fields (e.g. ``"link"``)
    whose own separator is supplied by the render context rather than the template, so
    the literal immediately preceding that tag is dropped here to avoid a doubled or
    dangling separator. Either kind of removal can orphan its other neighbour (e.g. a
    ``" | "`` left with nothing after it but a tab); a cleanup pass drops any literal
    that is both a removal's neighbour and now dangling at a tab or a paragraph edge.
    """
    ordered = sorted(items, key=lambda it: it[0])

    for start, end, _tag, field in ordered:
        if end > len(text):
            raise RuntimeError(
                f"{field}: span [{start}:{end}] exceeds paragraph length {len(text)}: {text!r}"
            )
        chunk = text[start:end]
        if "\t" in chunk:
            raise RuntimeError(
                f"{field}: span [{start}:{end}] contains a tab: {chunk!r}. "
                "Map date fields after the tab, not through it."
            )
        if "\n" in chunk or "\r" in chunk:
            raise RuntimeError(
                f"{field}: span [{start}:{end}] contains a line break: {chunk!r}."
            )

    raw: list[_Segment] = []
    cursor = 0
    prev_field: str | None = None
    for start, end, tag, field in ordered:
        if start < cursor:
            lo, hi = min(start, cursor), max(end, cursor)
            raise RuntimeError(
                f"Overlapping header field spans: {prev_field!r} and {field!r} "
                f"both claim {text[lo:hi]!r}"
            )
        if start > cursor:
            raw.extend(_split_literal(text, cursor, start, slices))
        if tag or end > start:
            raw.append(_Segment(text=tag, donor_offset=start, kind="tag", field=field))
        cursor = max(cursor, end)
        prev_field = field
    if cursor < len(text):
        raw.extend(_split_literal(text, cursor, len(text), slices))

    removed: set[int] = set()
    if drop_hyperlink_literals:
        for i, seg in enumerate(raw):
            if seg.kind != "text":
                continue
            donor = docx_text.slice_at(slices, seg.donor_offset)
            if donor is not None and donor.in_hyperlink:
                removed.add(i)

    if render_owned_separator_before:
        for i, seg in enumerate(raw):
            if seg.kind != "tag" or seg.field not in render_owned_separator_before:
                continue
            j = i - 1
            while j in removed:
                j -= 1
            if j >= 0 and raw[j].kind == "text" and _is_separator_literal(raw[j].text):
                removed.add(j)

    kept = [(i, seg) for i, seg in enumerate(raw) if i not in removed]

    final: list[_Segment] = []
    for pos, (i, seg) in enumerate(kept):
        is_removal_neighbor = (i - 1) in removed or (i + 1) in removed
        if seg.kind == "text" and is_removal_neighbor and _is_separator_literal(seg.text):
            prev_seg = final[-1] if final else None
            next_seg = kept[pos + 1][1] if pos + 1 < len(kept) else None
            dangling = (
                prev_seg is None
                or prev_seg.kind in ("tab", "break")
                or next_seg is None
                or next_seg.kind in ("tab", "break")
            )
            if dangling:
                continue
        final.append(seg)

    return [seg for seg in final if seg.kind != "text" or seg.text]


def rebuild_paragraph(
    paragraph: Paragraph, segments: list["_Segment"], slices: list[RunSlice]
) -> None:
    """Rewrite a paragraph's inline content from `segments`, one run per segment.

    Removes every `w:r` and `w:hyperlink` child and inserts fresh runs where the first
    one stood (leaving `w:pPr`, bookmarks, and proofing marks alone). Because the
    replacement is total, a baked-in hyperlink disappears as a side effect — callers must
    NOT strip hyperlinks beforehand, or spans measured against the original text will no
    longer line up (this is exactly how the project date lost its tab stop).
    """
    p = paragraph._p
    old_children = [c for c in p if c.tag in (_R_TAG, _HYPERLINK_TAG)]
    if not old_children:
        if segments:
            raise RuntimeError("Cannot tag a paragraph with no runs.")
        return

    anchor = old_children[0]
    new_runs = []
    for seg in segments:
        donor = docx_text.slice_at(
            slices, seg.donor_offset, skip_hyperlinks=(seg.kind == "tag")
        )
        run_el = _run_shell(donor)
        if seg.kind == "tab":
            run_el.append(OxmlElement("w:tab"))
        elif seg.kind == "break":
            run_el.append(OxmlElement("w:br"))
        else:
            _append_text(run_el, seg.text)
        new_runs.append(run_el)

    for run_el in new_runs:
        anchor.addprevious(run_el)
    for child in old_children:
        p.remove(child)


def retag_paragraph(
    paragraph: Paragraph,
    items: list[tuple[int, int, str, str]],
    *,
    render_owned_separator_before: frozenset[str] = frozenset(),
) -> None:
    """Replace mapped character spans in `paragraph` with Jinja tags.

    Each surviving literal keeps the formatting of whichever source run covered it; each
    tag inherits formatting from the (non-hyperlink) run at its span's start. A
    `<w:tab/>` between spans is preserved as a real tab element, never a literal
    ``"\\t"`` inside a `w:t`. This is the one rebuild path both header tagging and
    skills tagging use, so the two can never diverge in how they treat formatting.
    """
    slices = docx_text.paragraph_run_slices(paragraph)
    text = docx_text.paragraph_text(paragraph)
    segments = build_segments(
        text, slices, items, render_owned_separator_before=render_owned_separator_before
    )
    rebuild_paragraph(paragraph, segments, slices)


def replace_span_with_tag(
    paragraph: Paragraph, span: CharSpan, tag: str, *, field: str = "field"
) -> None:
    """Replace characters ``[start:end)`` in the paragraph with a single-run Jinja tag.

    Surrounding text keeps its own runs' formatting; a `<w:tab/>` outside the span
    survives as a real tab element. A span containing a tab raises — map date fields
    after the tab, not through it.
    """
    if span.start == span.end and not tag:
        return
    retag_paragraph(paragraph, [(span.start, span.end, tag, field)])


def _para_by_id(doc, paragraph_id: int) -> Paragraph:
    """Return the body paragraph at `paragraph_id`."""
    paras = doc.paragraphs
    if paragraph_id < 0 or paragraph_id >= len(paras):
        raise RuntimeError(f"Paragraph id {paragraph_id} out of range (0..{len(paras) - 1}).")
    return paras[paragraph_id]


def build_name_profile(doc, profile: TemplateProfile) -> None:
    """Tag the mapped name paragraph as ``{{ name }}``."""
    paragraph = _para_by_id(doc, profile.name_paragraph_id)
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Name line has no runs to tag.")
    set_run_text(runs[0], "{{ name }}")
    for extra in runs[1:]:
        paragraph._p.remove(extra._r)


def build_contact_profile(doc, profile: TemplateProfile) -> None:
    """Tag the mapped contact paragraph as a RichText placeholder."""
    paragraph = _para_by_id(doc, profile.contact.paragraph_id)
    strip_hyperlinks(paragraph)
    runs = paragraph.runs
    if not runs:
        raise RuntimeError("Contact line has no runs to tag.")
    set_run_text(runs[0], "{{r contact }}")
    for extra in runs[1:]:
        paragraph._p.remove(extra._r)


def _tag_mapped_header(
    doc,
    header_mapping,
    tag_for: dict[str, str],
    *,
    render_owned_separator_before: frozenset[str] = frozenset(),
) -> Paragraph:
    """Replace a header paragraph's mapped spans with tags, preserving runs and tabs.

    Spans are measured against the paragraph's text AS UPLOADED, including any baked-in
    hyperlink — callers must not strip hyperlinks before calling this. `retag_paragraph`
    removes them as a side effect of replacing every run, which is what keeps offsets
    valid (stripping first shortens the text the spans were measured against and slides
    every later span left — this is exactly how a project's date lost its tab stop).
    """
    paragraph = _para_by_id(doc, header_mapping.header_paragraph_id)

    items: list[tuple[int, int, str, str]] = []
    for name, field in header_mapping.fields.items():
        if not field.present or field.span is None or name not in tag_for:
            continue
        if field.span.paragraph_id != header_mapping.header_paragraph_id:
            other = _para_by_id(doc, field.span.paragraph_id)
            replace_span_with_tag(other, field.span, tag_for[name], field=name)
            continue
        items.append((field.span.start, field.span.end, tag_for[name], name))

    if not items:
        return paragraph

    retag_paragraph(
        paragraph, items, render_owned_separator_before=render_owned_separator_before
    )
    return paragraph


def build_experience_profile(doc, profile: TemplateProfile, *, noto_num_id: str | None) -> None:
    """Loop-tag the experience section from the confirmed mapping."""
    mapping = profile.experience
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, profile)
    header = _tag_mapped_header(
        doc,
        mapping.header,
        {
            "company": "{{ job.company }}",
            "location": "{{ job.location }}",
            "dates": "{{ job.dates }}",
        },
    )
    if mapping.title.present and mapping.title.span is not None:
        title_para = _para_by_id(doc, mapping.title.span.paragraph_id)
        replace_span_with_tag(title_para, mapping.title.span, "{{ job.title }}")
    elif mapping.title_paragraph_id is not None:
        title_para = _para_by_id(doc, mapping.title_paragraph_id)
        if title_para.runs:
            set_run_text(title_para.runs[0], "{{ job.title }}")
            for extra in title_para.runs[1:]:
                title_para._p.remove(extra._r)
    else:
        raise RuntimeError("Experience mapping is missing a job title.")

    title_para = (
        _para_by_id(doc, mapping.title.span.paragraph_id)
        if mapping.title.present and mapping.title.span is not None
        else _para_by_id(doc, mapping.title_paragraph_id)  # type: ignore[arg-type]
    )
    bullet = _para_by_id(doc, mapping.bullet_paragraph_id)
    retarget_bullet(bullet, noto_num_id)
    tag_bullet(bullet, "{{ bullet }}")

    # Insert clones before the (still-present) prototype header, then drop originals.
    anchor = header
    anchor._p.addprevious(make_para("{%p for job in experience %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(title_para._p))
    anchor._p.addprevious(make_para("{%p for bullet in job.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    _delete_paragraphs(victims)


def build_education_profile(doc, profile: TemplateProfile, *, noto_num_id: str | None) -> None:
    """Loop-tag the education section from the confirmed mapping."""
    mapping = profile.education
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, profile)
    header = _tag_mapped_header(
        doc,
        mapping.header,
        {
            "school": "{{ edu.school }}",
            "location": "{{ edu.location }}",
            "dates": "{{ edu.dates }}",
        },
    )
    degree = _para_by_id(doc, mapping.degree_paragraph_id)
    retarget_bullet(degree, noto_num_id)
    tag_bullet(degree, "{{ edu.degree_line }}")

    if mapping.detail_paragraph_id is not None:
        detail = _para_by_id(doc, mapping.detail_paragraph_id)
        if detail._p is degree._p:
            detail_p = copy.deepcopy(degree._p)
            degree._p.addnext(detail_p)
            detail = Paragraph(detail_p, degree._parent)
            tag_bullet(detail, "{{ detail }}")
        else:
            retarget_bullet(detail, noto_num_id)
            tag_bullet(detail, "{{ detail }}")
    else:
        detail_p = copy.deepcopy(degree._p)
        degree._p.addnext(detail_p)
        detail = Paragraph(detail_p, degree._parent)
        tag_bullet(detail, "{{ detail }}")

    anchor = header
    anchor._p.addprevious(make_para("{%p for edu in education %}"))
    anchor._p.addprevious(copy.deepcopy(header._p))
    anchor._p.addprevious(copy.deepcopy(degree._p))
    anchor._p.addprevious(make_para("{%p for detail in edu.details %}"))
    anchor._p.addprevious(copy.deepcopy(detail._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    _delete_paragraphs(victims)
    if detail._p.getparent() is not None and detail not in victims:
        # Drop a temporary degree clone that was inserted beside the source bullet.
        delete(detail)


def build_projects_profile(doc, profile: TemplateProfile, *, noto_num_id: str | None) -> None:
    """Loop-tag the projects section from the confirmed mapping."""
    mapping = profile.projects
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, profile)

    tag_for = {
        "name": "{{ proj.name }}",
        "tech": "{{ proj.tech }}",
        "date": "{{ proj.date }}",
    }
    fields = dict(mapping.header.fields)
    if mapping.link.present and mapping.link.span is not None:
        fields["link"] = OptionalSpan(present=True, span=mapping.link.span)
        tag_for["link"] = "{{r proj.link }}"
    header_mapping = mapping.header.model_copy(update={"fields": fields})
    # The baked-in hyperlink, if any, is removed by `_tag_mapped_header`'s rebuild — not
    # stripped here first. `mapping.link.span` was measured against the paragraph WITH
    # the hyperlink still present; stripping it first would shorten the text and shift
    # every later offset left, which used to swallow the date's tab into the link tag.
    # `render_owned_separator_before` drops the literal " | " before the link tag,
    # because `render.py` supplies that separator itself, only when a link is present.
    header_para = _tag_mapped_header(
        doc, header_mapping, tag_for, render_owned_separator_before=frozenset({"link"})
    )

    bullet = _para_by_id(doc, mapping.bullet_paragraph_id)
    retarget_bullet(bullet, noto_num_id)
    tag_bullet(bullet, "{{ bullet }}")

    anchor = header_para
    anchor._p.addprevious(make_para("{%p for proj in projects %}"))
    anchor._p.addprevious(copy.deepcopy(header_para._p))
    anchor._p.addprevious(make_para("{%p for bullet in proj.bullets %}"))
    anchor._p.addprevious(copy.deepcopy(bullet._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    _delete_paragraphs(victims)


def build_skills_profile(doc, profile: TemplateProfile) -> None:
    """Loop-tag the skills section from the confirmed mapping."""
    mapping = profile.skills
    assert mapping is not None
    victims = _section_body_paragraphs(doc, mapping.heading_paragraph_id, profile)
    prototype = _para_by_id(doc, mapping.prototype_paragraph_id)

    # A separate run per tag — rather than collapsing the whole line into one, as the
    # prior implementation did — is what keeps the label's bold and the entries' plain
    # formatting from the upload. Same tradeoff legacy `build_skills` documents.
    items = sorted(
        [
            (
                mapping.label_span.start,
                mapping.label_span.end,
                "{{ group.label }}",
                "skills_label",
            ),
            (
                mapping.body_span.start,
                mapping.body_span.end,
                "{{ group.entries }}",
                "skills_body",
            ),
        ],
        key=lambda it: it[0],
    )
    retag_paragraph(prototype, items)
    shrink_bullet_marker(prototype)

    anchor = prototype
    anchor._p.addprevious(make_para("{%p for group in skills %}"))
    anchor._p.addprevious(copy.deepcopy(prototype._p))
    anchor._p.addprevious(make_para("{%p endfor %}"))

    _delete_paragraphs(victims)


def _section_body_paragraphs(doc, heading_id: int, profile: TemplateProfile) -> list[Paragraph]:
    """Return current body paragraphs of a section (after heading, before next heading)."""
    heading = _para_by_id(doc, heading_id)
    ends: list[str] = []
    if profile.education and profile.education.heading_paragraph_id != heading_id:
        ends.append(profile.education.heading_text)
    if profile.experience.heading_paragraph_id != heading_id:
        ends.append(profile.experience.heading_text)
    if profile.projects and profile.projects.heading_paragraph_id != heading_id:
        ends.append(profile.projects.heading_text)
    if profile.skills and profile.skills.heading_paragraph_id != heading_id:
        ends.append(profile.skills.heading_text)

    seen_heading = False
    body: list[Paragraph] = []
    for para in list(doc.paragraphs):
        if para._p is heading._p:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        text = (para.text or "").strip()
        if text in ends or text.upper() in {e.upper() for e in ends}:
            break
        body.append(para)
    return body


def _delete_paragraphs(paragraphs: list[Paragraph]) -> None:
    """Delete the given paragraph objects from the document."""
    for para in paragraphs:
        if para._p.getparent() is not None:
            delete(para)


def build_from_profile(
    src: Path,
    dst: Path,
    profile: TemplateProfile,
) -> None:
    """Tag `src` using `profile` and write the result to `dst`."""
    doc = docx.Document(str(src))
    noto_num_id = None
    if profile.normalization.normalize_bullet_font:
        noto_num_id = discover_noto_num_id(doc)

    build_name_profile(doc, profile)
    build_contact_profile(doc, profile)

    # Build sections bottom-up (later headings first) so earlier paragraph indices stay
    # valid for still-pending sections. Deletion of a later section does not shift
    # earlier heading ids.
    builders: list[tuple[int, object]] = []
    builders.append((profile.experience.heading_paragraph_id, "experience"))
    if profile.enabled.education and profile.education is not None:
        builders.append((profile.education.heading_paragraph_id, "education"))
    if profile.enabled.projects and profile.projects is not None:
        builders.append((profile.projects.heading_paragraph_id, "projects"))
    if profile.enabled.skills and profile.skills is not None:
        builders.append((profile.skills.heading_paragraph_id, "skills"))
    builders.sort(key=lambda t: t[0], reverse=True)

    for _hid, kind in builders:
        if kind == "experience":
            build_experience_profile(doc, profile, noto_num_id=noto_num_id)
        elif kind == "education":
            build_education_profile(doc, profile, noto_num_id=noto_num_id)
        elif kind == "projects":
            build_projects_profile(doc, profile, noto_num_id=noto_num_id)
        elif kind == "skills":
            build_skills_profile(doc, profile)

    if profile.normalization.normalize_bullet_font:
        normalize_bullet_numbering(doc)
    if profile.normalization.force_single_spacing:
        normalize_single_spacing(doc)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------


def build_legacy(src: Path | None = None, dst: Path | None = None) -> int:
    """Build using the hard-coded Google Docs section headings (original behaviour)."""
    src = src or config.BASELINE_TEMPLATE_PATH
    dst = dst or config.DEFAULT_TEMPLATE_PATH

    if not src.exists():
        print(
            f"ERROR: {src} not found.\n"
            "Export your resume from Google Docs (File > Download > Microsoft Word) "
            "and save it there."
        )
        return 1

    doc = docx.Document(str(src))
    bounds = find_sections(doc)

    missing = [s for s in ("WORK EXPERIENCES", "PROJECTS", "SKILLS") if s not in bounds]
    if missing:
        print(
            f"ERROR: could not find section heading(s): {', '.join(missing)}.\n"
            "The build script locates sections by their exact all-caps heading text. "
            "If you renamed a heading in the Google Doc, update SECTIONS in this script "
            "or install a template profile via the Template tab."
        )
        return 1

    paras = doc.paragraphs

    if "EDUCATION" not in bounds:
        print(
            "ERROR: could not find section heading: EDUCATION.\n"
            "The build script locates sections by their exact all-caps heading text."
        )
        return 1

    edu_start, edu_end = bounds["EDUCATION"]
    exp_start, exp_end = bounds["WORK EXPERIENCES"]
    proj_start, proj_end = bounds["PROJECTS"]
    skill_start, skill_end = bounds["SKILLS"]

    education_entries = split_entries(paras[edu_start:edu_end])
    experience_entries = split_entries(paras[exp_start:exp_end])
    project_entries = split_entries(paras[proj_start:proj_end])
    skill_paras = paras[skill_start:skill_end]

    print(
        f"found {len(education_entries)} education, "
        f"{len(experience_entries)} experience entries, "
        f"{len(project_entries)} projects"
    )

    noto_num_id = discover_noto_num_id(doc)

    build_name(doc)
    build_contact(doc)
    build_education(doc, education_entries, noto_num_id=noto_num_id)
    build_experience(doc, experience_entries, noto_num_id=noto_num_id)
    build_projects(doc, project_entries, noto_num_id=noto_num_id)
    build_skills(doc, skill_paras)
    normalize_bullet_numbering(doc)
    normalize_single_spacing(doc)

    dst.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dst))
    print(f"wrote {dst}")
    return 0


def build(
    src: Path | None = None,
    dst: Path | None = None,
    profile: TemplateProfile | None = None,
    profile_path: Path | None = None,
) -> int:
    """Build a tagged template, using a profile when provided or present on disk.

    When neither `profile` nor a readable profile file is available, falls back to
    legacy hard-coded headings.
    """
    from .template_profile import load_profile

    src = src or config.BASELINE_TEMPLATE_PATH
    dst = dst or config.DEFAULT_TEMPLATE_PATH
    if profile is None and profile_path is not None:
        profile = load_profile(profile_path)
    if profile is None:
        profile = load_profile()

    if profile is None:
        return build_legacy(src, dst)

    try:
        build_from_profile(src, dst, profile)
    except Exception as exc:
        print(f"ERROR: profile build failed: {exc}")
        return 1
    print(
        f"wrote {dst} (profile v{profile.schema_version}; "
        f"sections: experience"
        f"{'+education' if profile.enabled.education else ''}"
        f"{'+projects' if profile.enabled.projects else ''}"
        f"{'+skills' if profile.enabled.skills else ''})"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry: optional ``--from``, ``--profile``, ``--out``, ``--workspace``."""
    import argparse
    import sys

    from . import workspace

    parser = argparse.ArgumentParser(description="Build main_template.docx from a baseline export.")
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=None,
        help="Baseline DOCX (default: templates/original_export.docx).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Tagged output path (default: templates/main_template.docx).",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=None,
        help="Template profile JSON (default: templates/template_profile.json if present).",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Ignore any profile and use hard-coded section headings.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="ID",
        help="Build against this profile instead of the active one (this invocation only).",
    )
    args = parser.parse_args(argv)
    try:
        workspace.bootstrap(workspace_id=args.workspace)
    except workspace.WorkspaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.legacy:
        return build_legacy(args.source, args.out)
    return build(args.source, args.out, profile_path=args.profile)


if __name__ == "__main__":
    raise SystemExit(main())
