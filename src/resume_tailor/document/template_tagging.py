"""Tagging a paragraph: header/bullet tags, loops, and span-preserving segment rebuilds."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Literal

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from . import docx_text, template_xml
from .docx_text import RunSlice
from .template_profile import CharSpan


# --------------------------------------------------------------------------------------
# Tagging
# --------------------------------------------------------------------------------------
def tag_header(paragraph: Paragraph, fields: list[str], *, tail_field: str) -> None:
    """Tag a header line of the form `<bold> | <plain>\\t<date>`.

    Runs before the tab receive `fields` in order; the run holding the tab keeps it and
    the text after the tab becomes `tail_field`. Working run-by-run rather than rewriting
    the paragraph is what preserves the bold prefix and the right-aligned tab stop.
    """
    tab_idx = template_xml.tab_run_index(paragraph)
    runs = paragraph.runs

    # Everything before the tab carries the leading fields.
    lead = runs[:tab_idx]
    for i, run in enumerate(lead):
        template_xml.set_run_text(run, fields[i] if i < len(fields) else "")

    # More fields than runs: insert plain runs instead of merging into the bold run.
    if len(fields) > len(lead) and lead:
        anchor = lead[-1]
        for field in fields[len(lead) :]:
            plain = template_xml.clone_run_after(anchor, field)
            template_xml.strip_bold(plain)
            anchor = plain

    runs = paragraph.runs
    tab_idx = template_xml.tab_run_index(paragraph)

    # The tab run keeps its tab; the date follows it.
    tab_run = runs[tab_idx]
    element_tab = template_xml.has_tab_element(tab_run)
    after_tab = tab_run.text.split("\t", 1)[1] if "\t" in tab_run.text else ""

    if after_tab or tab_idx == len(runs) - 1:
        # Tab and date share one run.
        if element_tab:
            template_xml.set_run_text(tab_run, tail_field, keep_tabs=True)
        else:
            template_xml.set_run_text(tab_run, "\t" + tail_field)
        for extra in runs[tab_idx + 1 :]:
            template_xml._drop_run(extra)
    else:
        # Tab and date are in separate runs; keep that split so the date keeps its own
        # formatting (the tab run is sometimes bold, the date never is).
        if element_tab:
            template_xml.set_run_text(tab_run, "", keep_tabs=True)
        else:
            template_xml.set_run_text(tab_run, "\t")
        template_xml.set_run_text(runs[tab_idx + 1], tail_field)
        for extra in runs[tab_idx + 2 :]:
            template_xml._drop_run(extra)

def tag_bullet(paragraph: Paragraph, expr: str) -> None:
    """Collapse a bullet to a single tagged run, keeping its list formatting."""
    runs = paragraph.runs
    template_xml.collapse_runs(runs, expr)

def build_loop(
    entry: list[Paragraph],
    anchor: Paragraph,
    *,
    outer: str,
    inner: str,
) -> None:
    """Insert a cloned, tagged entry wrapped in for-loops, before `anchor`."""
    anchor._p.addprevious(template_xml.make_para(outer))
    for para in entry:
        anchor._p.addprevious(copy.deepcopy(para._p))
    anchor._p.addprevious(template_xml.make_para("{%p endfor %}"))
    _ = inner

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
    for a, b in zip(points, points[1:], strict=False):
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
) -> list[_Segment]:
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
    paragraph: Paragraph, segments: list[_Segment], slices: list[RunSlice]
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
    """Return the body paragraph at `paragraph_id`, including one inside a table cell.

    Recomputed on every call, never cached: `template_analyze._load_paras` and this
    function must enumerate identically via `docx_text.iter_document_paragraphs`
    (`CharSpan.paragraph_id` is an index into that exact sequence), and several build
    steps insert or delete paragraphs mid-build, which shifts every later id — a cached
    list would silently return the wrong paragraph the moment that happens.
    """
    paras = [p for p, _location in docx_text.iter_document_paragraphs(doc)]
    if paragraph_id < 0 or paragraph_id >= len(paras):
        raise RuntimeError(f"Paragraph id {paragraph_id} out of range (0..{len(paras) - 1}).")
    return paras[paragraph_id]
