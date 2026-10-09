"""Importing a .docx's sections: experience, projects, education, skills and lists."""

from __future__ import annotations

from ..content.data import (
    Education,
    Experience,
    ListItem,
    Project,
    SkillGroup,
)
from ..document import (
    entry_structure,
    field_candidates,
    header_fields,
)
from ..document.analysis_types import _Para
from ..document.render import parse_range
from . import import_common


def _import_experience_entries(
    body: list[_Para], taken_ids: set[str]
) -> tuple[list[Experience], list[str]]:
    warnings: list[str] = []
    entries: list[Experience] = []
    for entry in entry_structure._split_entries(body):
        header_para = entry[0]
        header, _candidates = header_fields._entry_header_fields(
            entry, primary="company", secondary="location", date_field="dates"
        )
        company = import_common._field_text(entry, header, "company")
        location = import_common._field_text(entry, header, "location")
        dates_text = import_common._field_text(entry, header, "dates")

        rest = entry[1:]
        main_rest = header_fields._entry_main_paragraphs(entry)[1:]
        titles = [p for p in main_rest if not p.is_bullet and p.text.strip()]
        title = ""
        if titles:
            title_text = titles[0].text
            tab_idx = title_text.find("\t")
            if tab_idx < 0:
                title = title_text.strip()
            else:
                # The title line carries its own trailing tab-aligned date (a two-line
                # header where *each* line has one, e.g. an org affiliation followed by
                # a specific role's own date range) — keep just the title text out of
                # it, and fall back to its date only when the entry header itself had
                # none, rather than silently storing the raw "Title\tDate" text.
                title = title_text[:tab_idx].strip()
                if not dates_text:
                    dates_text = title_text[tab_idx + 1 :].strip()
        start, end = parse_range(dates_text) if dates_text else ("", "")
        bullet_paras = [p for p in rest if p.is_bullet]

        label = company or header_para.text.strip() or f"paragraph {header_para.id}"
        if not company:
            warnings.append(
                f"experience entry at paragraph {header_para.id}: could not detect a company name"
            )
        if not dates_text:
            warnings.append(f"{label}: no dates detected")
        if not bullet_paras:
            warnings.append(f"{label}: no bullets detected")

        entry_id = import_common._fresh_id(company or "role", taken_ids)
        entries.append(
            Experience(
                id=entry_id,
                company=company,
                title=title,
                location=location,
                start=start,
                end=end,
                bullets=import_common._import_bullets(bullet_paras, entry_id),
            )
        )
    return entries, warnings

def _import_project_entries(
    body: list[_Para], taken_ids: set[str]
) -> tuple[list[Project], list[str]]:
    warnings: list[str] = []
    entries: list[Project] = []
    for entry in entry_structure._split_entries(body):
        header_para = entry[0]
        text = header_para.text
        tab = text.find("\t")
        link, url, exclude_after = import_common._paragraph_hyperlink_target(
            header_para, limit=None if tab < 0 else tab
        )

        header, _candidates = header_fields._entry_header_fields(
            entry,
            primary="name",
            secondary="tech",
            date_field="date",
            exclude_after=exclude_after,
        )
        name = import_common._field_text(entry, header, "name")
        tech_text = import_common._field_text(entry, header, "tech")
        tech = [t.strip() for t in tech_text.split(",") if t.strip()]
        date_text = import_common._field_text(entry, header, "date")

        bullet_paras = [p for p in entry[1:] if p.is_bullet]

        label = name or header_para.text.strip() or f"paragraph {header_para.id}"
        if not name:
            warnings.append(
                f"project entry at paragraph {header_para.id}: could not detect a project name"
            )
        if not bullet_paras:
            warnings.append(f"{label}: no bullets detected")

        entry_id = import_common._fresh_id(name or "project", taken_ids)
        entries.append(
            Project(
                id=entry_id,
                name=name,
                tech=tech,
                date=date_text,
                link=link,
                url=url,
                bullets=import_common._import_bullets(bullet_paras, entry_id),
            )
        )
    return entries, warnings

def _import_education_entries(body: list[_Para]) -> tuple[list[Education], list[str]]:
    warnings: list[str] = []
    entries: list[Education] = []
    for entry in entry_structure._split_entries(body):
        header_para = entry[0]
        header, _candidates = header_fields._entry_header_fields(
            entry, primary="school", secondary="location", date_field="dates"
        )
        school = import_common._field_text(entry, header, "school")
        location = import_common._field_text(entry, header, "location")
        dates_text = import_common._field_text(entry, header, "dates")

        # Main-cell paragraphs only: a table layout's location/dates cell must not be
        # read as a degree line or a detail — see `_entry_main_paragraphs`.
        main_rest = header_fields._entry_main_paragraphs(entry)[1:]
        detail_paras = [p for p in main_rest if p.text.strip()]
        degree = ""
        gpa = ""
        show_gpa = False
        coursework: list[str] = []
        details: list[str] = []
        if detail_paras:
            degree_line = detail_paras[0].text.strip()
            gpa_m = import_common._GPA_RE.search(degree_line)
            if gpa_m:
                degree = degree_line[: gpa_m.start()].strip()
                gpa = gpa_m.group(1).strip()
                show_gpa = True
            else:
                degree = degree_line
            for p in detail_paras[1:]:
                text = p.text.strip()
                cw_m = import_common._COURSEWORK_RE.match(text)
                if cw_m:
                    coursework = [c.strip() for c in cw_m.group(1).split(",") if c.strip()]
                else:
                    details.append(text)

        label = school or header_para.text.strip() or f"paragraph {header_para.id}"
        if not school:
            warnings.append(
                f"education entry at paragraph {header_para.id}: could not detect a school name"
            )
        if not degree:
            warnings.append(f"{label}: no degree line detected")

        entries.append(
            Education(
                school=school,
                degree=degree,
                dates=dates_text,
                location=location,
                coursework=coursework,
                gpa=gpa,
                show_gpa=show_gpa,
                details=details,
            )
        )
    return entries, warnings

def _import_skill_groups(body: list[_Para]) -> tuple[list[SkillGroup], list[str]]:
    warnings: list[str] = []
    groups: list[SkillGroup] = []

    non_blank = [p for p in body if p.text.strip()]
    cross_pairs = field_candidates._skills_rows_across_cells(non_blank)
    if cross_pairs is not None:
        # Table layout: a label cell and a value cell, side by side — every row is one
        # group, unlike the single-paragraph path below where one line is one group.
        for lp, rp in cross_pairs:
            label = lp.text.strip()
            if label.endswith(":"):
                label = label[:-1].rstrip()
            items = [i.strip() for i in rp.text.split(",") if i.strip()]
            if label and items:
                groups.append(SkillGroup(label=label, items=items))
            else:
                warnings.append(
                    f"skills row at paragraph {lp.id} ({lp.text.strip()!r}) could not "
                    "be read as a label/value pair and was skipped"
                )
        return groups, warnings

    for p in non_blank:
        spans = field_candidates._skills_spans(p)
        if spans is None:
            warnings.append(
                f"skills line at paragraph {p.id} ({p.text.strip()!r}) is not "
                "'Label: item, item' shaped and was skipped"
            )
            continue
        label_span, body_span, _sep = spans
        label = p.text[label_span.start : label_span.end].strip()
        items = [i.strip() for i in p.text[body_span.start : body_span.end].split(",") if i.strip()]
        if label and items:
            groups.append(SkillGroup(label=label, items=items))
    return groups, warnings

def _import_list_items(
    body: list[_Para], vocabulary: set[str], taken_ids: set[str]
) -> list[ListItem]:
    items: list[ListItem] = []
    for p in body:
        text = p.text.strip()
        if not text:
            continue
        item_id = import_common._fresh_id(text, taken_ids)
        items.append(
            ListItem(id=item_id, text=text, tags=import_common._seed_tags(text, vocabulary))
        )
    return items
