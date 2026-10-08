"""PDF resume import (`resume_import_pdf`): synthetic PDFs only, no model or network."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter

from resume_tailor import config
from resume_tailor.importing import pdf_lines, pdf_patterns, resume_import_pdf
from resume_tailor.importing.pdf_lines import Line, PdfImportError, clean_lines
from resume_tailor.importing.resume_import_pdf import (
    ImportEntryLLM,
    ImportLLM,
    ImportSectionLLM,
    import_pdf,
)
from resume_tailor.infra import llm
from tests.pdf_fixtures import (
    T,
    image_only_pdf,
    make_pdf,
    single_column_resume,
    two_column_resume,
)


def _sections(resume):
    return {s.title: s for s in resume.sections}


def test_single_column_resume_becomes_a_structured_draft():
    imported = import_pdf(single_column_resume())
    resume = imported.resume
    assert resume.contact.name == "Alex Doe"
    assert resume.contact.email == "alex@example.com"
    assert resume.contact.phone == "(555) 010-0000"
    assert resume.contact.location == "Irvine, CA"
    assert resume.contact.linkedin == "https://www.linkedin.com/in/alexdoe"

    sections = _sections(resume)
    assert [s.kind for s in resume.sections] == [
        "education",
        "experience",
        "project",
        "skills",
        "list",
    ]
    school = sections["EDUCATION"].entries[0]
    assert school.school == "University of California, Irvine"
    assert school.degree == "B.S. Business Economics"
    assert school.gpa == "3.8"
    assert school.dates == "Expected Jun 2027"
    assert school.coursework == ["Corporate Finance", "Econometrics", "Accounting"]

    acme, beta = sections["EXPERIENCE"].entries
    assert (acme.company, acme.title, acme.location) == (
        "Acme Capital",
        "Summer Analyst",
        "New York, NY",
    )
    assert (acme.start, acme.end) == ("2025-06", "2025-08")
    # The wrapped bullet is one bullet again.
    assert acme.bullets[0].text == (
        "Built a discounted cash flow model in Excel for three retail companies and "
        "presented the valuation to the deal team"
    )
    assert len(acme.bullets) == 2
    assert beta.location == "Remote"

    project = sections["PROJECTS"].entries[0]
    assert (project.name, project.tech, project.start, project.end, project.date) == (
        "Portfolio Tracker",
        ["Python", "SQL"],
        "2025-03",
        "",
        "",
    )
    assert project.bullets[0].tags == ["python"]

    labels = [g.label for g in sections["SKILLS"].entries]
    assert labels == ["Tools", "Languages"]
    assert [i.text for i in sections["CERTIFICATIONS"].entries] == ["Bloomberg Market Concepts"]


def test_every_imported_word_comes_from_the_pdf():
    raw = single_column_resume()
    source = " ".join(ln.text for ln in pdf_lines.extract_lines(raw)[0])
    imported = import_pdf(raw)
    for bullet in imported.resume.all_bullets():
        for word in bullet.text.split():
            assert word in source


def test_two_column_resume_reads_each_column_in_turn():
    imported = import_pdf(two_column_resume())
    sections = _sections(imported.resume)
    assert list(sections) == ["SKILLS", "EDUCATION", "EXPERIENCE"]
    assert sections["SKILLS"].entries[0].items == ["Excel", "Tableau", "SQL", "Python"]
    gamma, delta = sections["EXPERIENCE"].entries
    assert (gamma.company, gamma.title) == ("Gamma Labs", "Data Intern")
    assert [b.text for b in gamma.bullets] == [
        "Cleaned 3 sales datasets in SQL for weekly reports",
        "Built a Tableau dashboard used by 5 managers",
    ]
    assert delta.start == "2025-01"
    assert sections["EDUCATION"].entries[0].dates == "2022 – 2026"
    assert any("grouped as 'Skills'" in w for w in imported.warnings)


def test_right_aligned_dates_do_not_look_like_a_second_column():
    lines, _links = pdf_lines.extract_lines(single_column_resume())
    assert any(ln.text == "Acme Capital\tJun 2025 – Aug 2025" for ln in lines)
    assert all(ln.x0 < 300 or ln.page == 0 and ln.top < 80 for ln in lines if not ln.bullet)


def test_image_only_pdf_is_rejected_with_advice():
    with pytest.raises(PdfImportError, match="no readable text"):
        import_pdf(image_only_pdf())


def test_password_protected_pdf_is_rejected():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(single_column_resume())))
    writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(PdfImportError, match="password"):
        import_pdf(buffer.getvalue())


def test_a_file_that_is_not_a_pdf_is_rejected():
    with pytest.raises(PdfImportError, match="readable PDF"):
        import_pdf(b"hello, not a pdf")


def test_too_many_pages_is_rejected():
    page = [T(40, 100, "Some text on a page that is long enough to count as text")]
    with pytest.raises(PdfImportError, match="pages"):
        import_pdf(make_pdf([page] * (pdf_lines.MAX_PAGES + 1)))


def test_running_footer_and_page_numbers_are_dropped():
    def page(n: int, body: list[T]) -> list[T]:
        return [*body, T(250, 770, "Alex Doe - Resume", size=8), T(560, 770, str(n), size=8)]

    raw = make_pdf(
        [
            page(
                1,
                [
                    T(40, 50, "Alex Doe", "B", 18),
                    T(40, 70, "alex@example.com"),
                    T(40, 100, "EXPERIENCE", "B", 11),
                    T(40, 116, "Acme\tJun 2024 - Aug 2024", "B"),
                    T(50, 130, "• Did the first thing with 3 tools"),
                ],
            ),
            page(
                2,
                [
                    T(40, 60, "PROJECTS", "B", 11),
                    T(40, 76, "Tracker", "B"),
                    T(50, 90, "• Tracked 25 holdings"),
                ],
            ),
        ]
    )
    lines = clean_lines(pdf_lines.extract_lines(raw)[0])
    texts = [ln.text for ln in lines]
    assert "Alex Doe - Resume" not in texts
    assert "1" not in texts and "2" not in texts
    assert "PROJECTS" in texts


def _line(text: str, **kw) -> Line:
    defaults = {"x0": 40.0, "top": 100.0, "size": 10.0, "rel_top": 0.2, "text_x0": 40.0}
    defaults.update(kw)
    defaults.setdefault("last_top", defaults["top"])
    return Line(text=text, **defaults)


def test_clean_up_ligatures_icons_and_bullet_glyphs():
    lines = clean_lines(
        [
            _line("ﬁnance intern"),
            _line(" Built a model", top=114, x0=50, text_x0=62),
            _line(" alex@example.com", top=128),
        ]
    )
    assert lines[0].text == "finance intern"
    assert lines[1].bullet and lines[1].text == "Built a model"
    assert lines[2].text == "alex@example.com"


def test_wrapped_lines_join_and_keep_real_hyphens():
    lines = clean_lines(
        [
            _line("• Led a cross-", x0=50, text_x0=62),
            _line("functional team of five and grew", x0=62, text_x0=62, top=112),
            _line("revenue by 10%", x0=62, text_x0=62, top=124),
            _line("• Automated recon­", x0=50, text_x0=62, top=136),
            _line("ciliation in Excel", x0=62, text_x0=62, top=148),
        ]
    )
    assert [ln.text for ln in lines] == [
        "Led a cross-functional team of five and grew revenue by 10%",
        "Automated reconciliation in Excel",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Summer 2025",
        "May '24 – Present",
        "Expected May 2027",
        "2023–Present",
        "Jan. 2024 - Mar. 2024",
        "06/2023 - 08/2023",
        "Fall 2024 to Spring 2025",
        "2026",
    ],
)
def test_date_shapes_are_recognised(text):
    assert pdf_patterns._DATE_FULL_RE.match(text)


def test_no_headings_keeps_everything_as_one_list():
    raw = make_pdf(
        [
            [
                T(40, 50, "Sam Poe", "B", 16),
                T(40, 70, "sam@example.com"),
                T(40, 100, "Worked at a coffee shop for two summers and trained new staff"),
                T(40, 114, "Volunteered at the food bank every weekend during school"),
            ]
        ]
    )
    imported = import_pdf(raw)
    assert imported.resume.contact.email == "sam@example.com"
    (section,) = imported.resume.sections
    assert section.kind == "list"
    assert len(section.entries) == 2
    assert any("No section headings" in w for w in imported.warnings)


# --------------------------------------------------------------------------------------
# Model-assisted structuring
# --------------------------------------------------------------------------------------


def _numbered_lines():
    return clean_lines(pdf_lines.extract_lines(single_column_resume())[0])


def _index(lines, text):
    return next(i for i, ln in enumerate(lines) if ln.text.startswith(text))


def _answer(lines, *, company="Acme Capital") -> ImportLLM:
    return ImportLLM(
        name_line=0,
        sections=[
            ImportSectionLLM(
                heading_line=_index(lines, "EXPERIENCE"),
                kind="experience",
                entries=[
                    ImportEntryLLM(
                        header_lines=[_index(lines, "Acme"), _index(lines, "Summer")],
                        primary=company,
                        secondary="Summer Analyst",
                        location="New York, NY",
                        dates="Jun 2025 – Aug 2025",
                        bullet_lines=[_index(lines, "Built"), _index(lines, "Screened")],
                    )
                ],
            ),
            ImportSectionLLM(
                heading_line=_index(lines, "SKILLS"),
                kind="skills",
                entries=[
                    ImportEntryLLM(
                        detail_lines=[_index(lines, "Tools"), _index(lines, "Languages")]
                    )
                ],
            ),
        ],
    )


def test_model_answer_is_used_with_line_numbers_for_bullets():
    lines = _numbered_lines()
    imported = import_pdf(single_column_resume(), use_model=True, ask=lambda _l: _answer(lines))
    sections = _sections(imported.resume)
    job = sections["EXPERIENCE"].entries[0]
    assert (job.company, job.title, job.start) == ("Acme Capital", "Summer Analyst", "2025-06")
    assert [b.text for b in job.bullets] == [
        lines[_index(lines, "Built")].text,
        lines[_index(lines, "Screened")].text,
    ]
    # Lines the model skipped are reported, never silently lost.
    assert any("weren't placed" in w and "Beta Bank" in w for w in imported.warnings)


def test_model_field_not_in_the_pdf_is_dropped():
    lines = _numbered_lines()
    imported = import_pdf(
        single_column_resume(),
        use_model=True,
        ask=lambda _l: _answer(lines, company="Goldman Sachs"),
    )
    job = _sections(imported.resume)["EXPERIENCE"].entries[0]
    assert job.company == "Acme Capital"  # fell back to the header's own text
    assert any("Goldman Sachs" in w for w in imported.warnings)


def test_model_failure_falls_back_to_the_built_in_reader():
    def boom(_lines):
        raise RuntimeError("connection refused")

    imported = import_pdf(single_column_resume(), use_model=True, ask=boom)
    assert "EXPERIENCE" in _sections(imported.resume)
    assert any("connection refused" in w for w in imported.warnings)


class _FakeMessages:
    def __init__(self, parsed, calls):
        self._parsed = parsed
        self._calls = calls

    def parse(self, **kwargs):
        self._calls.append(kwargs)
        return type("R", (), {"parsed_output": self._parsed, "stop_reason": "end_turn"})()


class _FakeClient:
    def __init__(self, parsed, calls):
        self.messages = _FakeMessages(parsed, calls)


def test_model_call_sends_plain_numbered_lines_and_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    lines = _numbered_lines()
    calls: list[dict] = []
    monkeypatch.setattr(llm, "client_for", lambda purpose: _FakeClient(_answer(lines), calls))

    first = resume_import_pdf._ask_model(lines)
    second = resume_import_pdf._ask_model(lines)
    assert first == second
    assert len(calls) == 1
    prompt = calls[0]["messages"][0]["content"]
    assert "[0] Alex Doe" in prompt
    assert "• Built a discounted cash flow model" in prompt
    assert "<w:" not in prompt
    assert calls[0]["output_format"] is ImportLLM
    assert list(tmp_path.glob("*.pdfimport.json"))
