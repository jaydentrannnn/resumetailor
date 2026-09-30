"""Hermetic tests for SimplifyJobs README parsing and filtering."""

from __future__ import annotations

from pathlib import Path

import pytest

from resume_tailor.apply import sources

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "simplify_readme.md"
_CATEGORIES = ["Software Engineering Internship Roles"]


@pytest.fixture
def readme_text() -> str:
    """Load the trimmed Simplify fixture README."""
    return _FIXTURE.read_text(encoding="utf-8")


def test_parse_readme_extracts_requested_section_only(readme_text):
    rows = sources.parse_readme(readme_text, _CATEGORIES)
    companies = {row.company for row in rows}
    assert "Acme Corp" in companies
    assert "Ignored Co" not in companies
    assert len(rows) == 6


def test_parse_readme_detects_emoji_flags(readme_text):
    rows = {row.job_id: row for row in sources.parse_readme(readme_text, _CATEGORIES)}
    assert rows["bbb22222-2222-2222-2222-222222222222"].citizenship_required == "Yes"
    assert rows["ccc33333-3333-3333-3333-333333333333"].sponsorship_ok == "No"
    assert rows["ddd44444-4444-4444-4444-444444444444"].advanced_degree is True
    assert "🎓" not in rows["ddd44444-4444-4444-4444-444444444444"].role
    assert sources.US_CITIZEN_FLAG in rows["bbb22222-2222-2222-2222-222222222222"].company


def test_filter_rows_applies_age_citizenship_degree_and_dedupe(readme_text):
    rows = sources.parse_readme(readme_text, _CATEGORIES)
    result = sources.filter_rows(
        rows,
        max_age_days=1,
        exclude_advanced_degree=True,
        exclude_citizenship=True,
        exclude_no_sponsorship=True,
        known_ids={"fff66666-6666-6666-6666-666666666666"},
    )
    assert [row.job_id for row in result.new_rows] == ["aaa11111-1111-1111-1111-111111111111"]
    assert result.total_candidates == 6
    assert result.age_filtered_count == 5
    assert result.excluded_citizenship == 1
    assert result.excluded_advanced_degree == 1
    assert result.excluded_no_sponsorship == 1
    assert result.already_known == 1


def test_filter_rows_keeps_no_sponsorship_when_not_excluded(readme_text):
    rows = sources.parse_readme(readme_text, _CATEGORIES)
    result = sources.filter_rows(
        rows,
        max_age_days=1,
        exclude_advanced_degree=False,
        exclude_citizenship=False,
        exclude_no_sponsorship=False,
        known_ids=set(),
    )
    ids = {row.job_id for row in result.new_rows}
    assert "ccc33333-3333-3333-3333-333333333333" in ids
    assert result.excluded_no_sponsorship == 0


def test_filter_rows_dedupes_known_ids(readme_text):
    rows = sources.parse_readme(readme_text, _CATEGORIES)
    result = sources.filter_rows(
        rows,
        max_age_days=1,
        exclude_advanced_degree=False,
        exclude_citizenship=False,
        exclude_no_sponsorship=False,
        known_ids={"aaa11111-1111-1111-1111-111111111111"},
    )
    assert all(row.job_id != "aaa11111-1111-1111-1111-111111111111" for row in result.new_rows)
    assert result.already_known >= 1


def test_fetch_readme_uses_httpx(monkeypatch):
    captured: dict = {}

    class _Response:
        status_code = 200
        text = "# Internships\n"
        headers = {}

        @staticmethod
        def raise_for_status():
            return None

    def _fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr(sources.httpx, "get", _fake_get)
    text = sources.fetch_readme("https://example.com/README.md")
    assert text.startswith("# Internships")
    assert captured["url"] == "https://example.com/README.md"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("31m", 0),
        ("2h", 0),
        ("0d", 0),
        ("5d", 5),
        ("2w", 14),
        ("3mo", 90),
        ("", None),
        ("yesterday", None),
    ],
)
def test_parse_age_normalizes_units(raw, expected):
    """Age tokens collapse minutes/hours to day 0 and scale weeks/months."""
    assert sources.parse_age(raw) == expected


def test_parse_readme_sets_age_days(readme_text):
    """Parsed rows carry a numeric ``age_days`` derived from the Age cell."""
    rows = {row.job_id: row for row in sources.parse_readme(readme_text, _CATEGORIES)}
    assert rows["aaa11111-1111-1111-1111-111111111111"].age_days == 0
    assert rows["eee55555-5555-5555-5555-555555555555"].age_days == 5


_SPEEDY = Path(__file__).resolve().parent / "fixtures" / "speedyapply_readme.md"


def test_parse_pipe_table_readme_extracts_usa_rows():
    text = _SPEEDY.read_text(encoding="utf-8")
    rows = sources.parse_pipe_table_readme(text, ["2027 USA SWE Internships", "USA Positions"])
    companies = {row.company for row in rows}
    assert companies == {"Microsoft", "DoorDash", "Figma", "Lyft", "Acme NewGrad"}
    assert "ForeignCo" not in companies
    by_company = {row.company: row for row in rows}
    assert by_company["Microsoft"].salary == "$52/hr"
    assert by_company["Microsoft"].age_days == 2
    assert "gh_jid=6143238004" in (by_company["Figma"].application_link or "")
    assert by_company["Figma"].age_days == 5


def test_list_sections_returns_levels():
    text = _SPEEDY.read_text(encoding="utf-8")
    sections = sources.list_sections(text)
    assert (2, "2027 USA SWE Internships") in sections
    assert (3, "FAANG") in sections or any(n == "FAANG" for _, n in sections)
    assert any("International" in n for _, n in sections)


def test_fetch_readme_etag_cache(tmp_path, monkeypatch):
    """Second fetch with 304 returns the cached body without re-downloading."""
    from resume_tailor import config

    monkeypatch.setattr(config, "APPLICATIONS_OUTPUT_DIR", tmp_path / "applications")
    bodies = {"count": 0}

    class _Resp:
        def __init__(self, status_code: int, text: str = "", etag: str = ""):
            self.status_code = status_code
            self.text = text
            self.headers = {"ETag": etag} if etag else {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

    def _fake_get(url, **kwargs):
        bodies["count"] += 1
        headers = kwargs.get("headers") or {}
        if headers.get("If-None-Match") == '"v1"':
            return _Resp(304)
        return _Resp(200, text="# cached body\n", etag='"v1"')

    monkeypatch.setattr(sources.httpx, "get", _fake_get)
    first = sources.fetch_readme("https://example.com/README.md")
    second = sources.fetch_readme("https://example.com/README.md")
    assert first == "# cached body\n"
    assert second == first
    assert bodies["count"] == 2


# --- more README formats, format detection, one-call fetch -------------------------

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TODAY = __import__("datetime").date(2026, 9, 29)


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def test_summary_h3_headings_are_sections():
    """zapplyjobs titles its sections ``<summary><h3>…</h3></summary>``."""
    text = _fixture("zapplyjobs_readme.md")
    assert (3, "Software Engineering") in sources.list_sections(text)
    assert (3, "Business & Operations") in sources.list_sections(text)
    rows = sources.parse_pipe_table_readme(text, ["Software Engineering"])
    assert [r.company for r in rows] == ["LabCorp", "Cisco", "Parsons"]
    labcorp, cisco, parsons = rows
    assert labcorp.application_link == "https://zapply.jobs/l/d/workday-labcorp-2632795"
    assert labcorp.age_days == 0 and cisco.age_days == 3
    assert parsons.age_days is None  # "Date unknown"
    business = sources.parse_pipe_table_readme(text, ["Business & Operations"])
    assert [r.company for r in business] == ["Deloitte"]


def test_jobright_rows_link_from_the_title_and_dates_resolve():
    text = _fixture("jobright_readme.md")
    rows = sources.parse_pipe_table_readme(text, ["Daily Job List"], today=_TODAY)
    assert [r.company for r in rows] == ["IBM", "IBM", "Nuclear Promise X"]
    first, second, third = rows
    assert first.role == "Delivery Consultant Intern"
    assert first.application_link == "https://jobright.ai/jobs/info/6a9e2880"
    assert (first.age_days, first.posted_at) == (0, "2026-09-29")
    assert (second.age_days, second.posted_at) == (2, "2026-09-27")
    # A date after today is last year's.
    assert third.posted_at == "2025-12-30"
    assert first.location == "Austin, TX, United States"


def test_vanshb03_rows_carry_flags_and_locations():
    text = _fixture("vanshb03_readme.md")
    rows = sources.parse_pipe_table_readme(text, ["The List"], today=_TODAY)
    assert [r.company for r in rows] == [
        "Quora",
        "Chicago Trading Company",
        "Chicago Trading Company",
    ]
    quora, ctc, quant = rows
    assert quora.application_link == "https://jobs.ashbyhq.com/quora/452afc2e"
    assert (quora.age_days, quora.posted_at) == (55, "2026-08-05")
    assert ctc.sponsorship_ok == "No" and ctc.role == "New Grad 2027: Associate Engineer"
    assert ctc.location == "Chicago, IL | New York, NY"
    assert quant.citizenship_required == "Yes"
    assert quant.location == "Chicago, IL | Austin, TX | NYC"


def test_company_link_table_one_row_per_link():
    text = _fixture("nwfintech_readme.md")
    rows = sources.parse_company_link_table(text, [])
    assert [(r.company, r.role) for r in rows] == [
        ("Akuna Capital", "Quant Developer"),
        ("Akuna Capital", "Software Engineer (C++)"),
        ("Akuna Capital", "Software Engineer (Python)"),
        ("Citadel", "Quant Researcher (PhD)"),
        ("Citadel", "Quant Trader"),
    ]
    assert rows[0].location == "Chicago"
    assert rows[0].application_link.endswith("?gh_jid=8021481")
    assert rows[3].advanced_degree is True
    assert (
        rows[4].application_link == "https://www.citadel.com/careers/details/quant-trader-intern/"
    )
    assert all(r.age_days == 0 and "age_unknown" in r.flags for r in rows)
    assert len({r.job_id for r in rows}) == 5
    only = sources.parse_company_link_table(text, ["Citadel"])
    assert {r.company for r in only} == {"Citadel"}
    assert sources.company_link_sections(text) == ["Akuna Capital", "Ansatz Capital", "Citadel"]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("simplify_readme.md", "simplify_html"),
        ("speedyapply_readme.md", "pipe_table"),
        ("zapplyjobs_readme.md", "pipe_table"),
        ("jobright_readme.md", "pipe_table"),
        ("vanshb03_readme.md", "pipe_table"),
        ("nwfintech_readme.md", "company_link_table"),
    ],
)
def test_detect_format(name, kind):
    assert sources.detect_format(_fixture(name)) == kind


def test_detect_format_none_and_fallback():
    assert sources.detect_format("# Nothing\n\nJust prose.\n") is None
    # The only signal (a legend's ``|---|``) reads no rows, and the Simplify rows carry
    # no ``<tr><td>`` signal: the fallback runs every parser and keeps the one with rows.
    html = (
        "## Legend\n| Key | Meaning |\n|---|---|\n| X | closed |\n"
        '## Roles\n<table><tbody>\n<tr class="row"><td>Acme</td><td>Intern</td><td>NYC</td>'
        '<td><a href="https://acme.com/job/1">Apply</a></td><td>1d</td></tr>\n</tbody></table>\n'
    )
    assert sources.detect_format(html) == "simplify_html"


def test_source_sections_lists_only_sections_with_rows():
    text = _fixture("zapplyjobs_readme.md")
    names = sources.source_sections("pipe_table", text)
    assert "Software Engineering" in names and "Business & Operations" in names
    assert "Live Job Boards" not in names


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3d", (3, "")),
        ("2026-08-30", (30, "2026-08-30")),
        ("Aug 01", (59, "2026-08-01")),
        ("Oct 01", (0, "2026-10-01")),  # two days ahead: a time-zone skew, this year
        ("Oct 05", (359, "2025-10-05")),
        ("Feb 30", (None, "")),
        ("soon", (None, "")),
        ("", (None, "")),
    ],
)
def test_parse_posted(raw, expected):
    assert sources.parse_posted(raw, today=_TODAY) == expected


def test_empty_categories_read_the_whole_readme():
    speedy = _fixture("speedyapply_readme.md")
    companies = {r.company for r in sources.parse_pipe_table_readme(speedy, [])}
    assert "Microsoft" in companies and "Acme NewGrad" in companies
    assert "ForeignCo" not in companies  # International sections stay out
    assert sources.parse_readme(_fixture("simplify_readme.md"), [])


def test_fetch_source_rows_dispatches_every_kind(monkeypatch):
    from resume_tailor.web.schemas import SourceConfig

    monkeypatch.setattr(sources, "fetch_readme", lambda url: _fixture("nwfintech_readme.md"))
    src = SourceConfig(id="nwf", kind="company_link_table", url="https://example.com/r.md")
    rows, errors = sources.fetch_source_rows(src)
    assert len(rows) == 5 and errors == []
    assert {r.source_id for r in rows} == {"nwf"}

    monkeypatch.setattr(
        sources,
        "board_rows",
        lambda s: (
            [sources.SourceRow(company="A", role="R", location="", age="", job_id="x")],
            ["board B: gone"],
        ),
    )
    board = SourceConfig(id="wl", kind="ats_board")
    rows, errors = sources.fetch_source_rows(board)
    assert rows[0].source_id == "wl" and errors == ["board B: gone"]


@pytest.mark.parametrize(
    ("pasted", "raw"),
    [
        (
            "https://github.com/zapplyjobs/Internships-2027",
            "https://raw.githubusercontent.com/zapplyjobs/Internships-2027/HEAD/README.md",
        ),
        (
            "https://github.com/SimplifyJobs/New-Grad-Positions/blob/dev/README.md",
            "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
        ),
        (
            "https://github.com/a/b/tree/main/",
            "https://raw.githubusercontent.com/a/b/main/README.md",
        ),
        ("https://github.com/a/b.git", "https://raw.githubusercontent.com/a/b/HEAD/README.md"),
        ("https://github.com/a/b#readme", "https://raw.githubusercontent.com/a/b/HEAD/README.md"),
        (
            "https://raw.githubusercontent.com/a/b/main/README.md",
            "https://raw.githubusercontent.com/a/b/main/README.md",
        ),
        ("https://example.com/jobs.md", "https://example.com/jobs.md"),
    ],
)
def test_raw_readme_url_maps_github_pages_to_raw(pasted, raw):
    assert sources.raw_readme_url(pasted) == raw


def test_job_list_rows_honour_the_sources_title_filters(monkeypatch):
    from resume_tailor.web.schemas import SourceConfig

    monkeypatch.setattr(sources, "fetch_readme", lambda url: _fixture("nwfintech_readme.md"))
    base = {"id": "nwf", "kind": "company_link_table", "url": "https://example.com/r.md"}
    everything, _ = sources.fetch_source_rows(SourceConfig(**base))
    assert everything

    word = everything[0].role.split()[0]
    kept, _ = sources.fetch_source_rows(SourceConfig(**base, include=[word]))
    skipped, _ = sources.fetch_source_rows(SourceConfig(**base, exclude=[word]))
    assert kept and all(word.lower() in r.role.lower() for r in kept)
    assert len(kept) + len(skipped) == len(everything)
