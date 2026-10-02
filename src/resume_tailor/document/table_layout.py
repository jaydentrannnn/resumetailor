"""Classifying a table-based resume layout (`layout="table"`): which cells hold what."""

from __future__ import annotations

from dataclasses import dataclass

from docx.oxml.ns import qn

from . import analysis_types, docx_text, entry_structure


@dataclass(frozen=True)
class TableShape:
    """The one top-level table a table-layout resume lives in."""

    index: int
    rows: int
    grid_cols: int

def classify_table_layout(
    doc,
    paras: list[analysis_types._Para],
    heading_fp_classes: frozenset[entry_structure._Fingerprint] = frozenset(),
) -> tuple[TableShape | None, list[analysis_types.Issue]]:
    """Decide whether this document's table forms ONE logical reading column (a
    `layout="table"` resume: content laid out top-to-bottom, the table used only to
    right-align dates/locations without tab stops) or a genuine multi-column/sidebar
    layout, which stays unsupported.

    Deliberately not width- or majority-based: a real single-column resume table puts
    a narrow label column beside a wide value column in one row (e.g. "Languages:" at
    1509 twips beside a 8859-twip value cell) and a wide main column beside a narrow
    date column in another, so no monotone width rule holds, and a linear resume is
    routinely *majority* two-cell rows (every entry header) against a minority of
    full-width rows (headings, bullets) — a full-width-fraction rule rejects exactly
    the documents it should accept. What actually holds for a linear table: it never
    runs two content streams in parallel. Bullets and section headings always live in
    the reading column (cell 0); nothing is vertically merged; no row holds three or
    more independently-populated cells.

    Returns `(None, issues)` with a single blocking issue on the first structural
    failure (checked in a fixed order so the message is deterministic), or
    `(TableShape, [])` for a linear table with no issues of its own — the caller still
    runs every other detector afterward, since "this table is linear" says nothing yet
    about whether a usable experience/contact mapping was actually found in it.
    """
    if docx_text.has_nested_tables(doc):
        return None, [
            analysis_types.Issue(
                code="nested_tables",
                message=(
                    "A table inside this document contains another table nested in one "
                    "of its cells. Only a single flat layout table is supported."
                ),
                blocking=True,
            )
        ]

    tables = doc.tables
    if not tables:
        return None, []
    if len(tables) > 1:
        return None, [
            analysis_types.Issue(
                code="multiple_tables",
                message=(
                    f"Document contains {len(tables)} separate tables. Only a single "
                    "table used as an invisible layout grid is supported — merge them "
                    "into one table in Word/Google Docs, or remove the extra one."
                ),
                blocking=True,
            )
        ]

    table = tables[0]
    if table._tbl.find(f".//{qn('w:vMerge')}") is not None:
        return None, [
            analysis_types.Issue(
                code="table_vertical_merge",
                message=(
                    "The document's table vertically merges cells, which is how a "
                    "sidebar layout spans a column across several rows. Only a table "
                    "used purely as an invisible single-column layout grid — no "
                    "vertical merges — is supported."
                ),
                blocking=True,
            )
        ]

    table_paras = [p for p in paras if p.location is not None and p.location.table == 0]
    if not table_paras:
        return None, []

    rows_seen = sorted({p.location.row for p in table_paras})  # type: ignore[union-attr]
    grid_cols = len(table.columns)

    for row in rows_seen:
        row_paras = [p for p in table_paras if p.location.row == row]  # type: ignore[union-attr]
        content_cells = row_paras[0].location.row_content_cells  # type: ignore[union-attr]
        if content_cells >= 3:
            return None, [
                analysis_types.Issue(
                    code="table_parallel_columns",
                    message=(
                        f"Row {row} of the table has {content_cells} independently "
                        "populated cells, so this document reads as more than two "
                        "parallel columns. Only a table used as an invisible "
                        "single-column layout grid is supported."
                    ),
                    blocking=True,
                )
            ]

    for p in table_paras:
        if p.is_bullet and p.location.cell != 0:  # type: ignore[union-attr]
            return None, [
                analysis_types.Issue(
                    code="table_sidebar_bullets",
                    message=(
                        f"Row {p.location.row}'s second cell contains bulleted text, "  # type: ignore[union-attr]
                        "so this document reads as two parallel columns. Only tables "
                        "used as an invisible single-column layout grid are "
                        "supported — a sidebar or two-column resume cannot be mapped."
                    ),
                    blocking=True,
                )
            ]

    found_heading = False
    for p in table_paras:
        stripped = p.text.strip()
        if not stripped or p.is_bullet or entry_structure._is_chrome(p.text):
            continue
        key, conf, _alias = entry_structure._classify_heading(stripped)
        if key is None or conf < 1.0:
            # Anything short of an exact alias match (a bare heuristic keyword hit —
            # "Technologies" in a company name matching the "skills" heuristic — or an
            # unaliased structural guess like "LEADERSHIP") needs the same structural
            # corroboration `_analyze_document`'s own loop requires for a sub-1.0 match:
            # not shaped like an entry header or the line right under one
            # (`_has_tab_like`, which — row-based — happens to catch both at once,
            # since a title paragraph shares its entry header's two-populated-cell
            # row), not earlier than the name/contact block, and — when the document
            # has a detectable heading-formatting class — a matching fingerprint.
            # Without this, an entry header ("Kidod Science & Technologies") or a
            # short all-caps field that merely looks heading-shaped by text alone (a
            # state abbreviation like "CA" in a location cell) reads as a sidebar
            # heading purely because it shares its row with the entry it belongs to.
            if analysis_types._has_tab_like(p):
                continue
            if key is None and (p.id < 2 or not entry_structure._looks_like_heading(stripped)):
                continue
            if heading_fp_classes and entry_structure._fingerprint(p) not in heading_fp_classes:
                continue
        found_heading = True
        loc = p.location
        assert loc is not None
        if loc.cell != 0 or loc.row_content_cells != 1:
            return None, [
                analysis_types.Issue(
                    code="table_sidebar_headings",
                    message=(
                        f"{stripped!r} (row {loc.row}) looks like a section heading "
                        "but shares its row with other content, which is how a "
                        "sidebar heading is laid out. Only tables used as an "
                        "invisible single-column layout grid are supported."
                    ),
                    blocking=True,
                )
            ]

    if not found_heading:
        return None, [
            analysis_types.Issue(
                code="table_no_headings",
                message=(
                    "This document's table contains no recognizable section heading, "
                    "so it reads as a data table rather than a resume layout grid."
                ),
                blocking=True,
            )
        ]

    return TableShape(index=0, rows=len(rows_seen), grid_cols=grid_cols), []
