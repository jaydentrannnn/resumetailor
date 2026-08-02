"""Regression tests for the template-rendering layer.

Every test here corresponds to a bug that actually shipped into a generated document
during development. All three produced files that were structurally well-formed XML and
passed a naive "does it parse" check, yet were rejected by Word or silently lost content
— so they are checked against the rendered XML, not against a parse.

These run without Word: they inspect the .docx package directly rather than converting to
PDF, so they stay fast and work on any platform.
"""

from __future__ import annotations

import zipfile

import pytest
from lxml import etree

from resume_tailor import config, data, render

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NOTO_MARKER_FONT = "Noto Sans Symbols"


@pytest.fixture(scope="module")
def rendered_docx(tmp_path_factory) -> zipfile.ZipFile:
    """Render the full master resume and return the output package."""
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")
    out = tmp_path_factory.mktemp("render") / "out.docx"
    render.render(data.load(), out=out)
    return zipfile.ZipFile(out)


@pytest.fixture(scope="module")
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

    "Tools & Languages" rendered as "Tools  Languages" until autoescape was enabled.
    """
    root = etree.fromstring(rendered)
    body_text = "".join(t.text or "" for t in root.iter(f"{W}t"))
    assert "Tools & Languages" in body_text
    assert "hybrid retrieval & reranking" in body_text


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
    assert "Github" in body_text


def test_each_project_keeps_its_own_url(tmp_path):
    """Baking one hyperlink into the template pointed every project at the same repo.

    Checks resolved targets, not relationship ids: distinct ids can still resolve to the
    same URL, which is precisely the bug.
    """
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")

    out = tmp_path / "out.docx"
    resume = data.load()
    render.render(resume, out=out)

    z = zipfile.ZipFile(out)
    root = etree.fromstring(z.read("word/document.xml"))
    rels = etree.fromstring(z.read("word/_rels/document.xml.rels"))
    target_of = {r.get("Id"): r.get("Target") for r in rels}

    R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    targets = {target_of.get(h.get(f"{R}id")) for h in root.iter(f"{W}hyperlink")}

    expected = {p.url for p in resume.projects if p.url}
    assert expected <= targets, f"missing project URLs: {expected - targets}"


def test_project_links_can_be_suppressed(tmp_path):
    """`include_project_links=False` drops the label, hyperlink, and leading separator.

    Contact hyperlinks (e.g. LinkedIn) still render — this flag only covers projects.
    The context key must remain a RichText so the template's `{{r }}` tag stays valid.
    """
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")

    out = tmp_path / "out.docx"
    resume = data.load()
    render.render(resume, out=out, include_project_links=False)

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
        if not any(run.find(f".//{W}tab") is not None for run in runs):
            continue

        company_run = next(
            (run for run in runs if "|" in "".join(t.text or "" for t in run.iter(f"{W}t"))),
            None,
        )
        location_run = next(
            (
                run
                for run in runs
                if "|" not in "".join(t.text or "" for t in run.iter(f"{W}t"))
                and run.find(f".//{W}tab") is None
                and "".join(t.text or "" for t in run.iter(f"{W}t")).strip()
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
    """Coursework from master_resume.json should appear as one Relevant Coursework bullet."""
    resume = data.load()
    assert resume.education, "fixture master resume needs an education entry"
    assert resume.education[0].coursework, "migration should have split coursework"
    root = etree.fromstring(rendered)
    body = "\n".join(
        "".join(t.text or "" for t in p.iter(f"{W}t")) for p in root.iter(f"{W}p")
    )
    assert "Relevant Coursework:" in body
    assert resume.education[0].coursework[0] in body


def test_gpa_appended_only_when_show_gpa(tmp_path):
    """GPA suffix appears on the degree line only when show_gpa is on and gpa is set."""
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")
    resume = data.load()
    assert resume.education
    edu = resume.education[0].model_copy(update={"gpa": "3.85", "show_gpa": False})
    resume = resume.model_copy(update={"education": [edu]})
    off = tmp_path / "gpa_off.docx"
    render.render(resume, out=off)
    with zipfile.ZipFile(off) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "GPA: 3.85" not in xml

    edu = edu.model_copy(update={"show_gpa": True})
    resume = resume.model_copy(update={"education": [edu]})
    on = tmp_path / "gpa_on.docx"
    render.render(resume, out=on)
    with zipfile.ZipFile(on) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "GPA: 3.85" in xml


def test_blank_github_omits_separator_in_contact_context():
    """A missing GitHub URL must not leave a dangling contact-line separator."""
    if not config.DEFAULT_TEMPLATE_PATH.exists():
        pytest.skip("template not built; run scripts/build_template.py")
    from docxtpl import DocxTemplate

    resume = data.load()
    contact = resume.contact.model_copy(update={"github": ""})
    resume = resume.model_copy(update={"contact": contact})
    tpl = DocxTemplate(config.DEFAULT_TEMPLATE_PATH)
    ctx = render.build_context(resume, tpl)
    # RichText xml should contain LinkedIn but not GitHub when github is blank.
    xml = ctx["contact"].xml
    assert "LinkedIn" in xml
    assert "GitHub" not in xml


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
