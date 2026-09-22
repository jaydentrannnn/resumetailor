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
    assert [row.job_id for row in result.new_rows] == [
        "aaa11111-1111-1111-1111-111111111111"
    ]
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
    rows = sources.parse_pipe_table_readme(
        text, ["2027 USA SWE Internships", "USA Positions"]
    )
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
