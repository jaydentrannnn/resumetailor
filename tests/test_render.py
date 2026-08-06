"""Regression tests for the template-rendering layer.

Every test here corresponds to a bug that actually shipped into a generated document
during development. All three produced files that were structurally well-formed XML and
passed a naive "does it parse" check, yet were rejected by Word or silently lost content
— so they are checked against the rendered XML, not against a parse.

These run without Word: they inspect the .docx package directly rather than converting to
PDF, so they stay fast and work on any platform.

Renders `tests.fixtures.synthetic_resume()` through the `built_template` fixture
(`conftest.py`) rather than a developer's own `data/master_resume.json` /
`templates/main_template.docx` — those may not exist at all on a clean checkout or in
CI, which previously forced most tests here into a conditional `pytest.skip`.
"""

from __future__ import annotations

import zipfile

import pytest
from lxml import etree

from resume_tailor import render
from tests.fixtures import synthetic_resume

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NOTO_MARKER_FONT = "Noto Sans Symbols"


@pytest.fixture
def rendered_docx(built_template, tmp_path) -> zipfile.ZipFile:
    """Render the synthetic resume and return the output package.

    Function-scoped deliberately, even though `built_template` (its one expensive
    dependency) stays session-scoped: this fixture reads `config.TEMPLATE_PROFILE_PATH`
    indirectly via `render.build_context`'s default `active_layout()` lookup, which
    `conftest.py`'s `_isolated_template_paths` redirects — but that redirect is itself
    function-scoped, and pytest sets up module-scoped fixtures *before* function-scoped
    ones for a given test. A module-scoped version of this fixture would therefore
    construct using whichever `TEMPLATE_PROFILE_PATH` was live before any isolation
    fixture ran — on a developer machine, a real, possibly stale profile — silently
    changing what renders for a reason invisible in the diff. Re-rendering per test is
    cheap here regardless: no Word/LibreOffice is involved, just docxtpl.
    """
    out = tmp_path / "out.docx"
    render.render(synthetic_resume(), template=built_template, out=out)
    return zipfile.ZipFile(out)


@pytest.fixture
def rendered(rendered_docx) -> bytes:
    """Return document.xml bytes from the rendered resume."""
    return rendered_docx.read("word/document.xml")


def _num_to_abstract(numbering_root: etree._Element) -> dict[str, str]:
    """Map list instance ids to abstract numbering definition ids."""
    mapping: dict[str, str] = {}
    for num in numbering_root.findall(f"{W}num"):
        nid = num.get(f"{W}numId")
        abs_el = num.find(f"{W}abstractNumId")
        if nid is not None and abs_el is not None:
            mapping[nid] = abs_el.get(f"{W}val", "")
    return mapping


def _lvl0_marker_font(numbering_root: etree._Element, abstract_id: str) -> str | None:
    """Return the ascii font name used for an abstract list's lvl0 bullet marker."""
    for anum in numbering_root.findall(f"{W}abstractNum"):
        if anum.get(f"{W}abstractNumId") != abstract_id:
            continue
        for lvl in anum.findall(f"{W}lvl"):
            if lvl.get(f"{W}ilvl") != "0":
                continue
            num_fmt = lvl.find(f"{W}numFmt")
            if num_fmt is None or num_fmt.get(f"{W}val") != "bullet":
                continue
            r_pr = lvl.find(f"{W}rPr")
            fonts = r_pr.find(f"{W}rFonts") if r_pr is not None else None
            return fonts.get(f"{W}ascii") if fonts is not None else None
    return None


def _run_is_bold(run: etree._Element) -> bool:
    """Return whether a run element is explicitly bold."""
    r_pr = run.find(f"{W}rPr")
    if r_pr is None:
        return False
    bold = r_pr.find(f"{W}b")
    if bold is None:
        return False
    val = bold.get(f"{W}val")
    return val is None or val not in ("0", "false")


def _paragraph_num_id(paragraph: etree._Element) -> str | None:
    """Return the list instance id for a paragraph, if any."""
    p_pr = paragraph.find(f"{W}pPr")
    if p_pr is None:
        return None
    num_pr = p_pr.find(f"{W}numPr")
    if num_pr is None:
        return None
    num_id = num_pr.find(f"{W}numId")
    return num_id.get(f"{W}val") if num_id is not None else None


def test_document_is_well_formed(rendered):
    etree.fromstring(rendered)


def test_no_python_repr_leaked_into_document(rendered):
    """`{{ group.items }}` resolved to dict.items and injected `<built-in method ...>`.

    Jinja tries attribute lookup before key lookup, so any context key that collides with
    a dict attribute renders as a method repr. The angle brackets became bogus XML
    elements, which Word rejected with a generic "cannot open the file".
    """
    text = rendered.decode("utf-8")
    assert "<built-in" not in text
    assert "method items" not in text
    assert "object at 0x" not in text


def test_ampersands_survive(rendered):
    """An unescaped "&" was swallowed as a malformed XML entity.

    `synthetic_resume()` places an ampersand in both a skills group item and a bullet
    (matching this test's original discovery: the bug did not depend on which context
    key carried it) so this stays a check on autoescaping generally, not one specific
    field.
    """
    root = etree.fromstring(rendered)
    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Data & Analytics" in body_text
    assert "Improved reliability & throughput" in body_text


def test_project_links_render_as_real_hyperlinks(rendered):
    """A plain `{{ }}` nested the link's run inside a `<w:t>`, which silently drops it.

    `w:t` may only contain characters, so the hyperlink vanished on read-back. The fix is
    docxtpl's `{{r }}` RichText tag.
    """
    root = etree.fromstring(rendered)
    links = list(root.iter(f"{W}hyperlink"))
    assert links, "no hyperlinks rendered"

    # A hyperlink must never be nested inside a text element.
    for t in root.iter(f"{W}t"):
        assert t.find(f".//{W}hyperlink") is None, "hyperlink nested inside w:t"

    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Repo" in body_text  # synthetic_resume()'s Project.link label


def test_hyperlinks_carry_internetlink_style_for_libreoffice(built_template, tmp_path):
    """LibreOffice drops PDF links unless hyperlink runs use a defined InternetLink style.

    Word keeps clickable links without this; Docker/soffice does not. Regression for the
    blue-but-dead LinkedIn/project PDFs.
    """
    out = tmp_path / "out.docx"
    render.render(synthetic_resume(), template=built_template, out=out)

    with zipfile.ZipFile(out) as z:
        doc = z.read("word/document.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")

    assert 'w:styleId="InternetLink"' in styles
    assert 'w:val="InternetLink"' in doc
    # Every hyperlink element should carry the style on at least one run.
    root = etree.fromstring(doc.encode("utf-8"))
    for link in root.iter(f"{W}hyperlink"):
        # OOXML attributes are in the wordprocessingml namespace under lxml.
        styles_on_runs = [
            r.get(f"{W}val") or r.get("val")
            for rPr in link.iter(f"{W}rPr")
            for r in rPr.iter(f"{W}rStyle")
        ]
        assert "InternetLink" in styles_on_runs, etree.tostring(link)[:200]


def test_each_project_keeps_its_own_url(built_template, tmp_path):
    """Baking one hyperlink into the template pointed every project at the same repo.

    Checks resolved targets, not relationship ids: distinct ids can still resolve to the
    same URL, which is precisely the bug.
    """
    out = tmp_path / "out.docx"
    resume = synthetic_resume()
    render.render(resume, template=built_template, out=out)

    z = zipfile.ZipFile(out)
    root = etree.fromstring(z.read("word/document.xml"))
    rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
    target_of = {r.get("Id"): r.get("Target") for r in rels}

    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    targets = {target_of.get(h.get(f"{R}id")) for h in root.iter(f"{W}hyperlink")}

    expected = {p.url for p in resume.projects if p.url}
    assert expected, "fixture must have at least one project URL to make this check meaningful"
    assert expected <= targets, f"missing project URLs: {expected - targets}"


def test_project_links_can_be_suppressed(built_template, tmp_path):
    """`include_project_links=False` drops the label, hyperlink, and leading separator.

    Contact hyperlinks (e.g. LinkedIn) still render — this flag only covers projects.
    The context key must remain a RichText so the template's `{{r }}` tag stays valid.
    """
    out = tmp_path / "out.docx"
    resume = synthetic_resume()
    render.render(resume, template=built_template, out=out, include_project_links=False)

    z = zipfile.ZipFile(out)
    root = etree.fromstring(z.read("word/document.xml"))
    rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
    target_of = {r.get("Id"): r.get("Target") for r in rels}

    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    targets = {target_of.get(h.get(f"{R}id")) for h in root.iter(f"{W}hyperlink")}
    project_urls = {p.url for p in resume.projects if p.url}
    assert not (project_urls & targets), f"project URLs still linked: {project_urls & targets}"

    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    for label in {p.link for p in resume.projects if p.link}:
        assert label not in body_text
    # Separator lived with the link RichText; a tech-run trailing " | " would remain.
    for proj in resume.projects:
        tech = ", ".join(proj.tech)
        assert f"{tech} |" not in body_text, f"dangling separator after {proj.name!r} tech"
    # Projects themselves must survive; only the link is gone.
    assert resume.projects[0].name in body_text


def test_bullet_spacing_is_normalised_within_each_section(rendered):
    """Every bullet in a section must share one spacing, the tightest source variant.

    The source resume mixes single-spaced and 1.15-spaced bullets *within* the experience
    section. Cloning the looser one inflated the document by roughly 15% of a line per
    bullet and pushed a one-page resume onto two.

    Normalisation is deliberately per-section, not global: experience and projects are
    visually distinct in the source, and flattening them together would change the look
    more than the loop actually requires.
    """
    root = etree.fromstring(rendered)

    section = None
    by_section: dict[str, set] = {}
    for p in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if text in ("EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS"):
            section = text
            continue
        if p.find(f".//{W}numPr") is None or section is None:
            continue
        pPr = p.find(f"{W}pPr")
        spacing = pPr.find(f"{W}spacing") if pPr is not None else None
        ind = pPr.find(f"{W}ind") if pPr is not None else None
        by_section.setdefault(section, set()).add(
            (
                spacing.get(f"{W}line") if spacing is not None else None,
                ind.get(f"{W}right") if ind is not None else None,
            )
        )

    assert by_section, "no bullets found in any section"
    for name, variants in by_section.items():
        assert len(variants) == 1, f"{name} has inconsistent bullet spacing: {variants}"


def test_all_content_paragraphs_use_single_spacing(rendered):
    """Every non-empty body paragraph must be single-spaced (line=240).

    Bullets use lineRule=exact so a substitute marker font cannot inflate auto height;
    other paragraphs use Word's Single (lineRule=auto).
    """
    root = etree.fromstring(rendered)
    bad: list[str] = []
    for p in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not text:
            continue
        pPr = p.find(f"{W}pPr")
        spacing = pPr.find(f"{W}spacing") if pPr is not None else None
        line = spacing.get(f"{W}line") if spacing is not None else None
        rule = spacing.get(f"{W}lineRule") if spacing is not None else None
        is_list = p.find(f".//{W}numPr") is not None
        expected_rule = "exact" if is_list else "auto"
        if line != "240" or rule != expected_rule:
            bad.append(f"{text[:40]!r} line={line} rule={rule}")
    assert not bad, "non-single spacing:\\n" + "\\n".join(bad)


def test_bullet_markers_use_noto_font(rendered_docx):
    """Every lvl0 bullet definition should draw markers in Noto Sans Symbols."""
    numbering = etree.fromstring(rendered_docx.read("word/numbering.xml"))
    fonts = {
        _lvl0_marker_font(numbering, anum.get(f"{W}abstractNumId"))
        for anum in numbering.findall(f"{W}abstractNum")
    }
    bullet_fonts = {font for font in fonts if font is not None}
    assert bullet_fonts, "no bullet numbering definitions found"
    assert bullet_fonts == {NOTO_MARKER_FONT}


def test_tailored_bullets_share_education_num_id(rendered):
    """Experience and project bullets should use the same list id as education."""
    root = etree.fromstring(rendered)
    section = None
    by_section: dict[str, set[str | None]] = {}
    for paragraph in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in paragraph.iter(f"{W}t")).strip()
        if text in ("EDUCATION", "WORK EXPERIENCES", "PROJECTS", "SKILLS"):
            section = text
            continue
        if section is None or _paragraph_num_id(paragraph) is None:
            continue
        by_section.setdefault(section, set()).add(_paragraph_num_id(paragraph))

    assert by_section["EDUCATION"], "education bullets missing"
    assert by_section["WORK EXPERIENCES"], "experience bullets missing"
    assert by_section["PROJECTS"], "project bullets missing"
    education_ids = by_section["EDUCATION"]
    assert len(education_ids) == 1
    education_num_id = next(iter(education_ids))
    assert by_section["WORK EXPERIENCES"] == {education_num_id}
    assert by_section["PROJECTS"] == {education_num_id}


def test_experience_header_location_is_not_bold(rendered):
    """Company stays bold; location after '|' must not inherit bold formatting."""
    root = etree.fromstring(rendered)
    section = None
    checked = 0
    for paragraph in root.iter(f"{W}p"):
        text = "".join(t.text or "" for t in paragraph.iter(f"{W}t"))
        stripped = text.strip()
        if stripped == "WORK EXPERIENCES":
            section = "WORK EXPERIENCES"
            continue
        if stripped == "PROJECTS":
            break
        if section != "WORK EXPERIENCES":
            continue
        if "|" not in text:
            continue
        runs = list(paragraph.findall(f"{W}r"))
        tab_idx = next(
            (i for i, run in enumerate(runs) if run.find(f".//{W}tab") is not None), None
        )
        if tab_idx is None:
            continue

        # The company span always starts at offset 0 (`_header_fields_from_text`), so
        # the first run is always part of it. Find the *last* run before the tab that
        # still contains "|" and search for location only after it — a tagged/rebuilt
        # header legitimately splits "Company | " into a `{{ job.company }}` tag run
        # plus its own literal " | " run, both bold; scanning the whole paragraph for
        # "the first run without a pipe" would catch the bare company-name run first.
        sep_idx = next(
            (
                i
                for i in range(tab_idx - 1, -1, -1)
                if "|" in "".join(t.text or "" for t in runs[i].iter(f"{W}t"))
            ),
            None,
        )
        if sep_idx is None:
            continue

        company_run = runs[0]
        location_run = next(
            (
                run
                for run in runs[sep_idx + 1 : tab_idx]
                if "".join(t.text or "" for t in run.iter(f"{W}t")).strip()
            ),
            None,
        )
        assert company_run is not None, f"missing company run in {text!r}"
        assert location_run is not None, f"missing location run in {text!r}"
        assert _run_is_bold(company_run), f"company run not bold in {text!r}"
        assert not _run_is_bold(location_run), f"location run is bold in {text!r}"
        checked += 1

    assert checked >= 1, "no experience header lines checked"


def test_contact_line_has_linkedin_hyperlink(rendered_docx, rendered):
    """Contact RichText should label LinkedIn and keep a real hyperlink relationship."""
    root = etree.fromstring(rendered)
    texts = [
        "".join(t.text or "" for t in p.iter(f"{W}t"))
        for p in root.iter(f"{W}p")
    ]
    contact = next((t for t in texts if "LinkedIn" in t), None)
    assert contact is not None, "contact line missing LinkedIn label"
    assert "https://www.linkedin.com" not in contact, "full LinkedIn URL should not print"
    # Hyperlink target lives in document.xml.rels, not in visible text.
    rels = rendered_docx.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "linkedin.com" in rels.lower()


def test_education_renders_coursework_from_master(rendered):
    """Coursework on a resume's education entry should appear as one Relevant Coursework
    bullet."""
    resume = synthetic_resume()
    assert resume.education, "fixture resume needs an education entry"
    assert resume.education[0].coursework, "fixture resume needs coursework"
    root = etree.fromstring(rendered)
    body = "\n".join(
        "".join(t.text or "" for t in p.iter(f"{W}t")) for p in root.iter(f"{W}p")
    )
    assert "Relevant Coursework:" in body
    assert resume.education[0].coursework[0] in body


def _with_education(resume, entries):
    """Replace the entries of every education-kind section with `entries`.

    `resume.education` is a read-only flattened view over `resume.sections` (see
    `data.MasterResume`), so `model_copy(update={"education": ...})` no longer has any
    effect — the update lands on the instance `__dict__`, which the property never reads.
    Mutating through `sections` is the real write path.
    """
    resume = resume.model_copy(deep=True)
    for section in resume.sections:
        if section.kind == "education":
            section.entries = list(entries)
    return resume


def test_gpa_appended_only_when_show_gpa(built_template, tmp_path):
    """GPA suffix appears on the degree line only when show_gpa is on and gpa is set."""
    resume = synthetic_resume()
    assert resume.education
    edu = resume.education[0].model_copy(update={"gpa": "3.85", "show_gpa": False})
    resume = _with_education(resume, [edu])
    off = tmp_path / "gpa_off.docx"
    render.render(resume, template=built_template, out=off)
    with zipfile.ZipFile(off) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "GPA: 3.85" not in xml

    edu = edu.model_copy(update={"show_gpa": True})
    resume = _with_education(resume, [edu])
    on = tmp_path / "gpa_on.docx"
    render.render(resume, template=built_template, out=on)
    with zipfile.ZipFile(on) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "GPA: 3.85" in xml


def test_blank_github_omits_separator_in_contact_context(built_template):
    """A missing GitHub URL must not leave a dangling contact-line separator."""
    from docxtpl import DocxTemplate

    resume = synthetic_resume()
    contact = resume.contact.model_copy(update={"github": ""})
    resume = resume.model_copy(update={"contact": contact})
    tpl = DocxTemplate(built_template)
    ctx = render.build_context(resume, tpl)
    # RichText xml should contain LinkedIn but not GitHub when github is blank.
    xml = ctx["contact"].xml
    assert "LinkedIn" in xml
    assert "GitHub" not in xml


def test_contact_fields_override_renders_exactly_those_in_order(built_template):
    """`build_context(contact_fields=...)` overrides the template's own order — this is
    the mechanism `include.contact_order` relies on for both reordering and omission."""
    from docxtpl import DocxTemplate

    resume = synthetic_resume()
    tpl = DocxTemplate(built_template)
    ctx = render.build_context(resume, tpl, contact_fields=["email", "linkedin"])
    xml = ctx["contact"].xml
    assert resume.contact.email in xml
    assert "LinkedIn" in xml
    # Fields omitted from the override must not render even though they are set.
    # `synthetic_resume()` deliberately gives contact/education/experience distinct
    # location strings (none a substring of another) so this can't false-negative from
    # an unrelated section that legitimately renders regardless of `contact_fields`.
    assert resume.contact.location not in xml
    assert "GitHub" not in xml
    # Exactly one separator between the two included fields, none elsewhere.
    assert xml.count("•") == 1


def test_contact_fields_none_falls_back_to_template_order(built_template):
    """Omitting `contact_fields` must reproduce the un-overridden render exactly."""
    from docxtpl import DocxTemplate

    resume = synthetic_resume()
    tpl = DocxTemplate(built_template)
    default_xml = render.build_context(resume, tpl)["contact"].xml

    tpl2 = DocxTemplate(built_template)
    overridden_xml = render.build_context(resume, tpl2, contact_fields=None)["contact"].xml
    assert default_xml == overridden_xml


def test_parse_month_inverts_format_month():
    assert render.parse_month("Jan 2023") == "2023-01"
    assert render.parse_month("June 2022") == "2022-06"
    assert render.format_month(render.parse_month("Jan 2023")) == "Jan 2023"


def test_parse_month_passes_through_unrecognized_text():
    """A bare year, "Present", or free text is passed through unchanged — the master
    file tolerates whatever a human wrote, exactly as `format_month` already does."""
    assert render.parse_month("Present") == "Present"
    assert render.parse_month("2020") == "2020"
    assert render.parse_month("Expected June 2027") == "Expected June 2027"


def test_parse_range_inverts_format_range():
    assert render.parse_range("Jan 2023 - Present") == ("2023-01", "Present")
    assert render.parse_range("Jun 2022 - Aug 2022") == ("2022-06", "2022-08")
    assert render.format_range(*render.parse_range("Jan 2023 - Aug 2023")) == "Jan 2023 - Aug 2023"


def test_parse_range_handles_a_bare_year_range_and_missing_separator():
    assert render.parse_range("2018 - 2022") == ("2018", "2022")
    assert render.parse_range("2020") == ("2020", "")


def test_degree_line_and_education_details_helpers():
    """Unit-level helpers used by build_context and fit overhead."""
    from resume_tailor.data import Education

    edu = Education(
        school="UCI",
        degree="B.S. Computer Science",
        dates="2023-2027",
        coursework=["Algorithms", "ML"],
        gpa="3.9",
        show_gpa=True,
        details=["Honors"],
    )
    assert render._degree_line(edu) == "B.S. Computer Science | GPA: 3.9"
    assert render._education_details(edu) == [
        "Relevant Coursework: Algorithms, ML",
        "Honors",
    ]
    edu2 = edu.model_copy(update={"show_gpa": False, "coursework": []})
    assert render._degree_line(edu2) == "B.S. Computer Science"
    assert render._education_details(edu2) == ["Honors"]
