"""Parse per-company link-table READMEs (``kind="company_link_table"``)."""

from __future__ import annotations

import re

from . import source_headings, source_pipe_table, source_rows

# --- per-company link tables (``kind="company_link_table"``) ----------------------

#: ``##`` headings in a company-link README that are not companies.
_NON_COMPANY_HEADINGS = {"contributing", "using this repository"}

#: Role abbreviations used by northwesternfintech's tables.
_ROLE_ABBREVIATIONS = {
    "qt": "Quant Trader",
    "qr": "Quant Researcher",
    "qd": "Quant Developer",
    "swe": "Software Engineer",
    "hw": "Hardware Engineer",
    "ml": "Machine Learning",
}

def _company_sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """``(company, start, end)`` for every ``##`` company heading."""
    heads = [
        (index, source_headings._normalize_heading_name(line[3:]))
        for index, line in enumerate(lines)
        if line.startswith("## ")
    ]
    out: list[tuple[str, int, int]] = []
    for position, (start, name) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        if name and name.casefold() not in _NON_COMPANY_HEADINGS:
            out.append((name, start, end))
    return out

def company_link_sections(text: str) -> list[str]:
    """Company names (the ``##`` headings) of a company-link-table README."""
    return [name for name, _s, _e in _company_sections(text.splitlines(keepends=True))]

def parse_company_link_table(text: str, categories: list[str]) -> list[source_rows.SourceRow]:
    """Parse a README of per-company ``|Role|Links|`` tables (northwesternfintech-style).

    The company is the ``##`` heading; each markdown link in a Links cell is its own
    row, its label (``C++``, ``PhD``) appended to the role. ``categories`` are company
    names; empty reads every company. These lists carry no dates and only list open
    postings, so rows are kept as new (``age_days=0``, flag ``age_unknown``), the way
    company watchlists treat an undated posting.
    """
    import hashlib

    lines = text.splitlines(keepends=True)
    wanted = {c.casefold() for c in categories}
    rows: list[source_rows.SourceRow] = []
    for company, start, end in _company_sections(lines):
        if wanted and company.casefold() not in wanted:
            continue
        location = ""
        in_table = False
        for line in lines[start + 1 : end]:
            stripped = line.strip()
            loc = re.match(r"^\*\*Locations?\*\*:\s*(.*)$", stripped, re.I)
            if loc:
                location = source_pipe_table._clean_pipe_text(loc.group(1))
                continue
            if not stripped.startswith("|"):
                continue
            cells = source_pipe_table._split_pipe_row(stripped)
            if [c.lower() for c in cells[:2]] == ["role", "links"]:
                in_table = True
                continue
            if not in_table or source_pipe_table._is_separator(stripped) or len(cells) < 2:
                continue
            raw_role = source_pipe_table._clean_pipe_text(cells[0])
            role = _ROLE_ABBREVIATIONS.get(raw_role.casefold(), raw_role)
            for label, href in re.findall(r"\[([^\]]*)\]\(([^)\s]+)\)", cells[1]):
                label = re.sub(r"[^\w+#./\s-]", "", label).strip()
                link = source_pipe_table._clean_apply_href(href)
                rows.append(
                    source_rows.SourceRow(
                        company=company,
                        role=f"{role} ({label})" if label else role,
                        location=location,
                        age="",
                        age_days=0,
                        job_id=hashlib.sha1(link.encode("utf-8")).hexdigest()[:16],
                        application_link=link,
                        advanced_degree=bool(re.search(r"\bph\.?d\b", label, re.I)),
                        flags=["age_unknown"],
                    )
                )
    return rows
