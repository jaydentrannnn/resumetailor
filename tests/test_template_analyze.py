"""Unit tests for deterministic DOCX template analysis (no Word / no network)."""

from __future__ import annotations

import io

import docx
import pytest
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from resume_tailor import template_analyze


def _add_bullet_numbering(document) -> str:
    """Install a minimal bullet abstract + num instance; return the numId string."""
    # python-docx creates numbering part lazily; force it via a style-based list then
    # fall back to a hand-rolled abstract if needed.
    numbering = document.part.numbering_part
    root = numbering.element

    abstract_id = "10"
    # Skip if we already added one in this document.
    for anum in root.findall(qn("w:abstractNum")):
        if anum.get(qn("w:abstractNumId")) == abstract_id:
            break
    else:
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), abstract_id)
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), "0")
        num_fmt = OxmlElement("w:numFmt")
        num_fmt.set(qn("w:val"), "bullet")
        lvl.append(num_fmt)
        abstract.append(lvl)
        # abstractNum elements must precede w:num
        first_num = root.find(qn("w:num"))
        if first_num is not None:
            first_num.addprevious(abstract)
        else:
            root.append(abstract)

    num_id = "20"
    for num in root.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            return num_id
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), num_id)
    abs_el = OxmlElement("w:abstractNumId")
    abs_el.set(qn("w:val"), abstract_id)
    num.append(abs_el)
    root.append(num)
    return num_id


def _make_bullet(document, text: str, num_id: str):
    """Append a list paragraph with the given numId."""
    paragraph = document.add_paragraph(text)
    pPr = paragraph._p.get_or_add_pPr()
    numPr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    nid = OxmlElement("w:numId")
    nid.set(qn("w:val"), num_id)
    numPr.append(ilvl)
    numPr.append(nid)
    pPr.append(numPr)
    return paragraph


def _docx_bytes(build) -> bytes:
    """Run `build(document)` and return the saved .docx bytes."""
    document = docx.Document()
    build(document)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _standard_resume(document) -> None:
    """Minimal single-column resume matching the legacy heading contract."""
    num_id = _add_bullet_numbering(document)
    document.add_paragraph("Ada Lovelace")
    document.add_paragraph("London • ada@example.com • LinkedIn")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("University of London | UK\t2018 - 2022")
    _make_bullet(document, "BSc Computer Science | GPA: 3.9", num_id)
    _make_bullet(document, "Relevant Coursework: Algorithms, Databases", num_id)
    document.add_paragraph("WORK EXPERIENCES")
    document.add_paragraph("Analytical Engines | London\t2022 - Present")
    document.add_paragraph("Software Engineer")
    _make_bullet(document, "Built numerical engines in Python.", num_id)
    document.add_paragraph("PROJECTS")
    document.add_paragraph("Note Engine | Python, FastAPI\t2024")
    _make_bullet(document, "Indexed research notes with embeddings.", num_id)
    document.add_paragraph("SKILLS")
    p = document.add_paragraph()
    run = p.add_run("Languages:")
    run.bold = True
    p.add_run(" Python, SQL")


def test_analyze_standard_resume_is_ready():
    """A well-formed single-column resume yields a suggested profile."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.ready is True
    assert result.suggested_profile is not None
    assert result.suggested_profile.enabled.experience is True
    assert result.suggested_profile.source_sha256 == template_analyze.sha256_bytes(raw)
    keys = {s.key for s in result.sections}
    assert keys == {"education", "experience", "projects", "skills"}


def _multi_section_resume(document) -> None:
    """Mirrors the real-world motivating case: three experience-shaped sections, one of
    them ("OTHER ACTIVITIES") unrecognized by any heading alias, plus a single-line
    (non-bulleted) education entry — both structural-detection edge cases."""
    num_id = _add_bullet_numbering(document)
    document.add_paragraph("Nina Dao")
    document.add_paragraph("nina@example.com")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("UC Irvine\tExpected June 2027")
    document.add_paragraph("B.A. in Business Administration")  # plain, not a Word bullet
    document.add_paragraph("WORK EXPERIENCE")
    document.add_paragraph("Langmaster JSC\tAug 2025 - Present")
    document.add_paragraph("Online Tutor")
    _make_bullet(document, "Tutored students in English.", num_id)
    document.add_paragraph("LEADERSHIP EXPERIENCE")
    document.add_paragraph("In the Green at UCI\tMay 2025 - Present")
    document.add_paragraph("Co-president")
    _make_bullet(document, "Oversaw club operations.", num_id)
    document.add_paragraph("OTHER ACTIVITIES")
    document.add_paragraph("Heartbeat Bazaar\tMar 2022 - Jun 2022")
    document.add_paragraph("Organizer")
    _make_bullet(document, "Directed fundraising events.", num_id)
    document.add_paragraph("SKILLS")
    sk = document.add_paragraph()
    run = sk.add_run("Languages:")
    run.bold = True
    sk.add_run(" Python, SQL")


def test_structural_fallback_detects_unaliased_experience_heading():
    """'OTHER ACTIVITIES' matches no known alias but is still recognised, structurally,
    as its own experience-shaped section rather than being absorbed into the section
    above it."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_multi_section_resume))
    other = next((s for s in result.sections if s.heading_text == "OTHER ACTIVITIES"), None)
    assert other is not None
    assert other.key == "experience"
    assert other.entry_count == 1
    assert other.bullet_count == 1


def test_all_three_experience_shaped_sections_detected_separately():
    """WORK EXPERIENCE, LEADERSHIP EXPERIENCE, and OTHER ACTIVITIES each become their own
    candidate — none absorbed into another."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_multi_section_resume))
    experience_headings = {s.heading_text for s in result.sections if s.key == "experience"}
    assert experience_headings == {"WORK EXPERIENCE", "LEADERSHIP EXPERIENCE", "OTHER ACTIVITIES"}


def test_generic_mode_suggested_when_multiple_same_kind_sections_found():
    """Three experience-kind headings cannot all keep their own title under one
    hard-coded fixed-mode heading, so the suggestion switches to generic mode."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_multi_section_resume))
    assert result.ready is True
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "generic"
    assert profile.heading_prototype is not None
    section_titles = {s.title for s in profile.sections}
    assert section_titles == {
        "EDUCATION", "WORK EXPERIENCE", "LEADERSHIP EXPERIENCE", "OTHER ACTIVITIES", "SKILLS",
    }


def test_fixed_mode_unchanged_for_a_single_heading_per_kind():
    """The ordinary case — one heading per kind — still suggests fixed mode, byte-for-byte
    the same profile shape as before generic mode existed."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_standard_resume))
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "fixed"
    assert profile.sections == []
    assert profile.heading_prototype is None


def test_plain_education_line_is_a_non_blocking_warning():
    """A degree line with no Word list bullet no longer blocks the install — `retarget_
    bullet` can convert it into one at build time — it only warns."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_multi_section_resume))
    assert result.ready is True
    assert not any(i.code == "no_education_bullets" for i in result.issues)
    assert any(
        i.code == "education_bullets_not_list" and not i.blocking for i in result.issues
    )


def test_structural_fallback_does_not_misclassify_the_name_line():
    """An all-caps name (a common style) must never be read as a section heading."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("JANE APPLESEED")
        document.add_paragraph("jane@example.com")
        document.add_paragraph("EXPERIENCE")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert {s.heading_text for s in result.sections} == {"EXPERIENCE"}
    assert result.suggested_profile is not None
    assert result.suggested_profile.name_paragraph_id == 0


def _spacer_multi_section_resume(document) -> None:
    """Mirrors the real-world motivating document: a blank paragraph before every
    heading, one right after every heading, and one between entries within a body that
    has more than one entry — exactly the pattern `_detect_spacing` looks for. Unlike
    `_multi_section_resume`/`_standard_resume` (both imported by
    `tests/test_template_build.py` and asserted spacer-free elsewhere), this fixture
    exists solely to exercise spacer detection."""
    num_id = _add_bullet_numbering(document)
    document.add_paragraph("Nina Dao")
    document.add_paragraph("nina@example.com")
    document.add_paragraph("")
    document.add_paragraph("EDUCATION")
    document.add_paragraph("")
    document.add_paragraph("UC Irvine\tExpected June 2027")
    _make_bullet(document, "B.A. in Business Administration", num_id)
    document.add_paragraph("")
    document.add_paragraph("WORK EXPERIENCE")
    document.add_paragraph("")
    document.add_paragraph("Langmaster JSC\tAug 2025 - Present")
    document.add_paragraph("Online Tutor")
    _make_bullet(document, "Tutored students in English.", num_id)
    document.add_paragraph("")
    document.add_paragraph("Garin JSC\tNov 2023 - May 2024")
    document.add_paragraph("Logistics Intern")
    _make_bullet(document, "Managed international logistics.", num_id)
    document.add_paragraph("")
    document.add_paragraph("LEADERSHIP EXPERIENCE")
    document.add_paragraph("")
    document.add_paragraph("In the Green at UCI\tMay 2025 - Present")
    document.add_paragraph("Co-president")
    _make_bullet(document, "Oversaw club operations.", num_id)
    document.add_paragraph("")
    document.add_paragraph("SKILLS")
    document.add_paragraph("")
    _make_bullet(document, "Languages: Python, SQL", num_id)


def test_spacer_donors_detected_on_a_blank_separated_document():
    """A majority of detected sections show a blank before, after, and (where more than
    one entry exists) between entries — all three runs get recorded, each one paragraph
    long since this fixture uses a single blank at every slot."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_spacer_multi_section_resume))
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "generic"
    assert len(profile.spacing.before_heading) == 1
    assert len(profile.spacing.after_heading) == 1
    assert len(profile.spacing.between_entries) == 1

    paras = {p.id: p.text for p in result.paragraphs}
    for run in (
        profile.spacing.before_heading,
        profile.spacing.after_heading,
        profile.spacing.between_entries,
    ):
        for pid in run:
            assert paras[pid].strip() == ""


def _rule_separated_resume(document) -> None:
    """Mirrors the real installed baseline: a horizontal rule *and* a blank under every
    heading, and two consecutive blanks at one entry boundary. Both shapes defeated
    single-paragraph spacer detection — the rule is chrome but not blank, and with two
    adjacent blanks neither one's neighbour is the bullet/header pair a boundary test
    looks for."""
    num_id = _add_bullet_numbering(document)
    rule = "_" * 60
    document.add_paragraph("Nina Dao")
    document.add_paragraph("nina@example.com")
    document.add_paragraph("")
    document.add_paragraph("EDUCATION")
    document.add_paragraph(rule)
    document.add_paragraph("")
    document.add_paragraph("UC Irvine\tExpected June 2028")
    _make_bullet(document, "B.A. in Business Administration", num_id)
    document.add_paragraph("")
    document.add_paragraph("EXPERIENCE")
    document.add_paragraph(rule)
    document.add_paragraph("")
    document.add_paragraph("Yellow Daisy\tAug 2022 - Jun 2024")
    document.add_paragraph("Co-founder")
    _make_bullet(document, "Raised $1,200 for surgery.", num_id)
    document.add_paragraph("")
    document.add_paragraph("")  # two blanks at this boundary, not one
    document.add_paragraph("Youth Opportunity\tSep 2021 - Oct 2021")
    document.add_paragraph("Ambassador")
    _make_bullet(document, "Designed social posts.", num_id)
    document.add_paragraph("")
    document.add_paragraph("INTERNSHIPS & PROGRAMS")
    document.add_paragraph(rule)
    document.add_paragraph("")
    document.add_paragraph("Deloitte\tFeb 2025 - May 2025")
    document.add_paragraph("Mentee")
    _make_bullet(document, "Exposure to financial analysis.", num_id)
    document.add_paragraph("")
    document.add_paragraph("Garin JSC\tNov 2023 - May 2024")
    document.add_paragraph("Audit Assistant")
    _make_bullet(document, "Tracked logistics.", num_id)
    document.add_paragraph("")
    document.add_paragraph("SKILLS")
    document.add_paragraph(rule)
    document.add_paragraph("")
    _make_bullet(document, "Technical: Canva, Excel", num_id)


def test_after_heading_run_captures_a_rule_plus_blank():
    """The paragraph at `body_start` is the horizontal rule, which is chrome but not
    blank. Detecting only a single *blank* found nothing here, and the rule was then
    deleted with the rest of the body — the section heading lost its underline."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_rule_separated_resume))
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "generic"

    paras = {p.id: p.text for p in result.paragraphs}
    run = profile.spacing.after_heading
    assert len(run) == 2
    assert set(paras[run[0]].strip()) == {"_"}  # the rule
    assert paras[run[1]].strip() == ""  # then the blank


def test_between_entries_run_survives_two_consecutive_blanks():
    """One boundary in this fixture uses two blanks and two use one. The modal length
    wins, so the document-wide gap stays one paragraph rather than being inflated by the
    single outlier — and, critically, is detected at all."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_rule_separated_resume))
    profile = result.suggested_profile
    assert profile is not None

    paras = {p.id: p.text for p in result.paragraphs}
    run = profile.spacing.between_entries
    assert len(run) == 1
    assert paras[run[0]].strip() == ""


def test_spacer_donors_absent_on_the_existing_multi_section_fixture():
    """`_multi_section_resume` has no blank paragraphs at all — every run stays empty,
    pinning that an ordinary (non-blank-separated) upload is unaffected by this feature."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_multi_section_resume))
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "generic"
    assert profile.spacing.before_heading == []
    assert profile.spacing.after_heading == []
    assert profile.spacing.between_entries == []


def test_spacer_donors_absent_under_fixed_mode():
    """`_standard_resume` has one heading per kind, so it stays on fixed mode — spacing
    detection never runs there (`build_generic` is never used to consume it)."""
    result = template_analyze.analyze_docx(raw=_docx_bytes(_standard_resume))
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "fixed"
    assert profile.spacing.before_heading == []
    assert profile.spacing.after_heading == []
    assert profile.spacing.between_entries == []


def test_spacing_profile_accepts_the_legacy_single_id_shape():
    """A `template_profile.json` written by the first cut of this feature stored one int
    (or null) per slot. It must still load rather than 500 the whole app."""
    from resume_tailor.template_profile import SpacingProfile

    legacy = SpacingProfile.model_validate(
        {"before_heading": 2, "after_heading": None, "between_entries": 13}
    )
    assert legacy.before_heading == [2]
    assert legacy.after_heading == []
    assert legacy.between_entries == [13]


def test_detected_section_uses_singular_project_kind():
    """`DetectedSection.kind` uses `GenericSectionKind`'s singular `"project"`, not
    `SectionCandidate.key`'s legacy plural `"projects"` — a resume with two
    projects-shaped headings must not crash `analyze_docx` with a pydantic
    `ValidationError` the first time this path is exercised."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("EXPERIENCE")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("SELECTED PROJECTS")
        document.add_paragraph("Note Engine\t2024")
        _make_bullet(document, "Indexed notes.", num_id)
        document.add_paragraph("PERSONAL PROJECTS")
        document.add_paragraph("Side App\t2023")
        _make_bullet(document, "Shipped solo.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.ready is True
    profile = result.suggested_profile
    assert profile is not None
    assert profile.section_mode == "generic"
    project_sections = [s for s in profile.sections if s.kind == "project"]
    assert len(project_sections) == 2


def test_analyze_renamed_experience_heading():
    """'PROFESSIONAL EXPERIENCE' maps to the experience section."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("PROFESSIONAL EXPERIENCE")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert any(s.key == "experience" for s in result.sections)
    assert result.suggested_profile is not None
    assert result.suggested_profile.enabled.education is False
    assert result.suggested_profile.enabled.projects is False


def test_analyze_missing_experience_is_blocking():
    """No experience heading → ready false with a blocker."""
    def build(document):
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("SKILLS")
        document.add_paragraph("Languages: Python")

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.ready is False
    assert any(i.code == "missing_experience" and i.blocking for i in result.issues)


def test_analyze_tables_are_blocking():
    """Tables are rejected as unsupported layouts."""
    def build(document):
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Acme"
        table.cell(0, 1).text = "Engineer"

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert any(i.code == "tables" and i.blocking for i in result.issues)


def test_validate_profile_hash_mismatch():
    """Installing with a profile from a different file is rejected."""
    raw_a = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw_a)
    assert result.suggested_profile is not None
    profile = result.suggested_profile

    raw_b = _docx_bytes(lambda d: (d.add_paragraph("Other"), d.add_paragraph("x@y.z")))
    issues = template_analyze.validate_profile_against_doc(profile, raw=raw_b)
    assert any(i.code == "hash_mismatch" and i.blocking for i in issues)


def test_contact_separator_detection():
    """Pipe-separated contact lines become ' | ' separators."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("City | a@b.co | LinkedIn")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Did work.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    assert "|" in result.suggested_profile.contact.separator


def _add_hyperlink(paragraph, text: str, url: str) -> None:
    """Append a real w:hyperlink run so analyze's has_hyperlink path fires."""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    rPr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    new_run.append(rPr)
    text_el = OxmlElement("w:t")
    text_el.text = text
    new_run.append(text_el)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def test_project_header_name_tech_github_no_overlap():
    """name | tech | Github\\tdate must not fold Github into the tech span."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        # Mirror the live resume: name | tech | Github\\tdates with a real hyperlink.
        p = document.add_paragraph(
            "Text-to-SQL Reward Fine-Tuning via RL | "
            "GRPO, Deeplearn, HuggingFace, SQL | "
        )
        _add_hyperlink(p, "Github", "https://github.com/example/repo")
        # Tab + dates as a following run (python-docx paragraph.text joins them).
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("Jan 2026 - Mar 2026")
        _make_bullet(document, "Built reward functions.", num_id)

    raw = _docx_bytes(build)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.ready is True
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    tech = projects.header.fields.get("tech")
    assert tech is not None and tech.present and tech.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    tech_preview = header_text[tech.span.start : tech.span.end]
    assert "Github" not in tech_preview
    assert "GRPO" in tech_preview
    assert projects.link.present is True
    assert projects.link.span is not None
    link_preview = header_text[projects.link.span.start : projects.link.span.end]
    assert link_preview == "Github"
    assert tech.span.end <= projects.link.span.start


def test_project_link_label_comes_from_hyperlink_text():
    """The link span is derived from the hyperlink's own text, not a fixed word list."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        p = document.add_paragraph("Note Engine | Python, FastAPI | ")
        _add_hyperlink(p, "Source", "https://example.com/source")
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("2024")
        _make_bullet(document, "Indexed notes.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    assert projects.link.present is True
    assert projects.link.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    assert header_text[projects.link.span.start : projects.link.span.end] == "Source"


def test_project_header_without_tech_does_not_duplicate_link_span():
    """'Name | Github\\tdate' maps only the link, not an overlapping tech span."""
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Name")
        document.add_paragraph("email@example.com")
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2020 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Shipped features.", num_id)
        document.add_paragraph("PROJECTS")
        p = document.add_paragraph("Solo Proj | ")
        _add_hyperlink(p, "Github", "https://github.com/example/solo")
        run = p.add_run()
        run._r.append(OxmlElement("w:tab"))
        p.add_run("Jan 2026")
        _make_bullet(document, "Shipped solo.", num_id)

    result = template_analyze.analyze_docx(raw=_docx_bytes(build))
    assert result.suggested_profile is not None
    projects = result.suggested_profile.projects
    assert projects is not None
    tech = projects.header.fields.get("tech")
    assert tech is None or not tech.present
    assert projects.link.present is True
    assert projects.link.span is not None
    header_text = next(
        p.text for p in result.paragraphs if p.id == projects.header.header_paragraph_id
    )
    assert header_text[projects.link.span.start : projects.link.span.end] == "Github"


def test_validate_rejects_tab_inside_span():
    """A mapped span that straddles a real tab is rejected as blocking."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.suggested_profile is not None
    profile = result.suggested_profile
    exp = profile.experience
    dates_span = exp.header.fields["dates"].span
    assert dates_span is not None
    bad_span = dates_span.model_copy(update={"start": dates_span.start - 1})
    bad_fields = dict(exp.header.fields)
    bad_fields["dates"] = bad_fields["dates"].model_copy(update={"span": bad_span})
    bad_profile = profile.model_copy(
        update={
            "experience": exp.model_copy(
                update={"header": exp.header.model_copy(update={"fields": bad_fields})}
            )
        }
    )
    issues = template_analyze.validate_profile_against_doc(bad_profile, raw=raw)
    assert any(i.code == "span_has_tab" and i.blocking for i in issues)


def test_validate_rejects_overlapping_spans():
    """Two mapped fields claiming the same text on one paragraph are rejected."""
    raw = _docx_bytes(_standard_resume)
    result = template_analyze.analyze_docx(raw=raw)
    assert result.suggested_profile is not None
    profile = result.suggested_profile
    exp = profile.experience
    company_span = exp.header.fields["company"].span
    assert company_span is not None
    bad_fields = dict(exp.header.fields)
    bad_fields["location"] = bad_fields["location"].model_copy(
        update={"span": company_span}
    )
    bad_profile = profile.model_copy(
        update={
            "experience": exp.model_copy(
                update={"header": exp.header.model_copy(update={"fields": bad_fields})}
            )
        }
    )
    issues = template_analyze.validate_profile_against_doc(bad_profile, raw=raw)
    assert any(i.code == "overlapping_spans" and i.blocking for i in issues)
