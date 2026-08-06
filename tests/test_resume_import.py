"""Tests for the deterministic DOCX -> MasterResume importer (no LLM, no network)."""

from __future__ import annotations

import io

import docx

from resume_tailor import resume_import, template_analyze
from resume_tailor.data import MasterResume
from tests.fixtures import (
    _add_bullet_numbering,
    _add_hyperlink,
    _docx_bytes,
    _full_featured_resume,
    _make_bullet,
    _multi_section_resume,
    _standard_resume,
)


def _import(build) -> resume_import.ImportedResume:
    """Analyze + import a synthetic docx built by `build`."""
    raw = _docx_bytes(build)
    result = template_analyze.analyze_docx(raw=raw)
    doc = docx.Document(io.BytesIO(raw))
    return resume_import.import_from_analysis(result, doc)


def test_full_featured_resume_round_trips_every_field():
    """Every field the source docx actually carries reaches the draft, and the draft
    is a fully valid MasterResume (round-trips through JSON, not just construction)."""
    imported = _import(_full_featured_resume)
    resume = imported.resume

    # Round-trips through full JSON serialization, not just in-memory construction.
    import json

    reloaded = MasterResume.model_validate(json.loads(json.dumps(resume.model_dump(mode="json"))))
    assert reloaded == resume

    assert resume.contact.name == "Jordan Rivera"
    assert resume.contact.email == "jordan@example.com"
    assert resume.contact.phone == "(555) 123-4567"
    assert resume.contact.location == "Irvine, CA"

    edu = resume.education[0]
    assert edu.school == "State University"
    assert edu.location == "Boston, MA"
    assert edu.dates == "2019 - 2023"
    assert edu.degree == "BS Computer Science"
    assert edu.coursework == ["Algorithms", "Databases"]

    exp = resume.experience[0]
    assert exp.company == "Example Corp"
    assert exp.location == "Remote"
    assert exp.title == "Software Engineer"
    assert exp.start == "2023"
    assert exp.end == "Present"
    assert len(exp.bullets) == 1
    assert exp.bullets[0].text == "Improved reliability & throughput for production services."

    proj = resume.projects[0]
    assert proj.name == "Note Engine"
    assert proj.tech == ["Python", "FastAPI"]
    assert proj.date == "2024"
    assert proj.link == "Github"
    assert proj.url == "https://github.com/jordanrivera/note-engine"
    assert len(proj.bullets) == 1

    skills = resume.skills[0]
    assert skills.label == "Tools"
    assert skills.items == ["Python", "Data & Analytics"]


def test_bullet_ids_are_entry_scoped_and_sequential():
    imported = _import(_full_featured_resume)
    exp_bullet = imported.resume.experience[0].bullets[0]
    proj_bullet = imported.resume.projects[0].bullets[0]
    assert exp_bullet.id == f"{imported.resume.experience[0].id}_b1"
    assert proj_bullet.id == f"{imported.resume.projects[0].id}_b1"


def test_known_tag_is_seeded_deterministically():
    """A bullet whose text names a known tag (e.g. "embeddings") gets it without any
    LLM call — the deterministic pass this whole module is built around."""
    imported = _import(_full_featured_resume)
    proj_bullet = imported.resume.projects[0].bullets[0]
    assert "embeddings" in proj_bullet.tags


def test_unmatched_bullet_gets_the_untagged_sentinel_and_is_counted():
    imported = _import(_full_featured_resume)
    exp_bullet = imported.resume.experience[0].bullets[0]
    assert exp_bullet.tags == [resume_import.UNTAGGED]
    assert imported.untagged_bullet_count >= 1
    assert any("untagged" in w.lower() for w in imported.warnings)


def test_entry_ids_collide_safely_across_kinds():
    """Two entries that would slugify to the same base (one experience, one project,
    both named 'Acme') must not collide — the second gets a `-2` suffix, the same
    collision suffixing `MasterResume._fill_entry_ids` already uses."""

    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Sam Rivers")
        document.add_paragraph("sam@example.com")
        document.add_paragraph("WORK EXPERIENCE")
        document.add_paragraph("Acme | Remote\t2022 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Built things.", num_id)
        document.add_paragraph("PROJECTS")
        document.add_paragraph("Acme | Python\t2023")
        _make_bullet(document, "Built a different thing.", num_id)

    imported = _import(build)
    exp_id = imported.resume.experience[0].id
    proj_id = imported.resume.projects[0].id
    assert exp_id != proj_id
    assert {exp_id, proj_id} == {"acme", "acme-2"}


def test_multi_section_resume_imports_every_experience_shaped_section():
    """Mirrors the analyzer's own motivating multi-section fixture: three
    experience-kind sections (one unaliased, 'OTHER ACTIVITIES') must all import,
    not just the first one found."""
    imported = _import(_multi_section_resume)
    experience_sections = [s for s in imported.resume.sections if s.kind == "experience"]
    assert len(experience_sections) == 3
    titles = {s.title for s in experience_sections}
    assert titles == {"WORK EXPERIENCE", "LEADERSHIP EXPERIENCE", "OTHER ACTIVITIES"}
    for s in experience_sections:
        assert len(s.entries) == 1
        assert len(s.entries[0].bullets) == 1


def test_standard_resume_imports_cleanly_with_no_warnings():
    imported = _import(_standard_resume)
    assert imported.warnings == []
    assert imported.resume.experience[0].company == "Analytical Engines"
    assert imported.resume.education[0].school == "University of London"


def test_contact_hyperlinks_are_extracted_when_real():
    """A real `w:hyperlink` (not just visible "LinkedIn"/"GitHub" text) is resolved to
    its actual target URL via `docx_text.hyperlink_target`."""

    def build(document):
        document.add_paragraph("Jordan Rivera")
        p = document.add_paragraph("Irvine, CA | jordan@example.com | ")
        _add_hyperlink(p, "LinkedIn", "https://linkedin.com/in/jordanrivera")

    imported = _import(build)
    assert imported.resume.contact.linkedin == "https://linkedin.com/in/jordanrivera"


def test_contact_plain_text_profile_url_is_recovered():
    """A profile URL typed as plain text (no real hyperlink — common when an export
    loses them) is still recognized, and a bare "/" inside it is not mistaken for a
    field separator."""

    def build(document):
        document.add_paragraph("Nina Dao")
        document.add_paragraph(
            "nina@example.com • +1 (626) 206-6947 • www.linkedin.com/in/ngocdao2006"
        )

    imported = _import(build)
    assert imported.resume.contact.linkedin == "www.linkedin.com/in/ngocdao2006"
    assert imported.resume.contact.location == ""


def test_phone_with_leading_parenthesis_is_not_truncated():
    """`_PHONE_RE` requires its match to start on a digit, so "(555) 123-4567" would
    lose its opening paren without the explicit restore."""

    def build(document):
        document.add_paragraph("Jordan Rivera")
        document.add_paragraph("Irvine, CA • jordan@example.com • (555) 123-4567")

    imported = _import(build)
    assert imported.resume.contact.phone == "(555) 123-4567"


def test_two_line_header_title_does_not_leak_its_own_trailing_date():
    """A title line that itself carries a tab-aligned date ('Organizer and Marketing
    Member\\tJan. 2023 - Feb. 2023') must contribute only its text to `title`, using
    its date as a fallback only when the entry header itself had none."""

    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Nina Dao")
        document.add_paragraph("nina@example.com")
        document.add_paragraph("OTHER ACTIVITIES")
        document.add_paragraph("Heartbeat Bazaar\tMar 2022 - Jun 2022")
        document.add_paragraph("Organizer\tJan 2023 - Feb 2023")
        _make_bullet(document, "Directed fundraising events.", num_id)

    imported = _import(build)
    entry = imported.resume.experience[0]
    assert entry.title == "Organizer"
    assert "\t" not in entry.title
    # The primary header's own dates win over the title line's fallback date.
    assert (entry.start, entry.end) == ("2022-03", "2022-06")


def test_education_gpa_and_coursework_parsed_from_the_degree_line():
    def build(document):
        num_id = _add_bullet_numbering(document)
        document.add_paragraph("Ada Lovelace")
        document.add_paragraph("ada@example.com")
        document.add_paragraph("EDUCATION")
        document.add_paragraph("State University\t2018 - 2022")
        _make_bullet(document, "BSc Computer Science | GPA: 3.9", num_id)
        _make_bullet(document, "Relevant Coursework: Algorithms, Databases", num_id)
        document.add_paragraph("WORK EXPERIENCES")
        document.add_paragraph("Acme | Remote\t2022 - Present")
        document.add_paragraph("Engineer")
        _make_bullet(document, "Built things.", num_id)

    imported = _import(build)
    edu = imported.resume.education[0]
    assert edu.degree == "BSc Computer Science"
    assert edu.gpa == "3.9"
    assert edu.show_gpa is True
    assert edu.coursework == ["Algorithms", "Databases"]
