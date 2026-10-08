"""Tailored experience dates follow the original resume's month style and separator."""

from resume_tailor.document import date_style, render


def test_detects_the_dominant_month_style_and_separator():
    texts = ["Acme Corp\tJuly 2026 \u2013 Present", "Beta\tMarch 2024 \u2013 June 2025", "Jan 2020 - Feb 2021"]
    assert date_style.detect_in_texts(texts) == {"month": "full", "separator": " \u2013 "}


def test_numeric_and_abbreviated_dot_styles():
    assert date_style.detect_in_texts(["07/2026-Present"]) == {"month": "numeric", "separator": "-"}
    assert date_style.detect_in_texts(["Jan. 2020 \u2014 Feb. 2021"])["month"] == "abbr_dot"


def test_no_ranges_means_no_style():
    assert date_style.detect_in_texts(["Led a team of four", "Irvine, CA"]) is None


def test_format_range_defaults_to_the_legacy_output():
    assert render.format_range("2026-07", "Present") == "Jul 2026 - Present"


def test_format_range_follows_the_detected_style():
    style = {"month": "full", "separator": " \u2013 "}
    assert render.format_range("2026-07", "Present", style) == "July 2026 \u2013 Present"
    assert render.format_range("2024-03", "2025-06", style) == "March 2024 \u2013 June 2025"
    dotted = {"month": "abbr_dot", "separator": " - "}
    assert render.format_range("2020-01", "2021-09", dotted) == "Jan. 2020 - Sept. 2021"
    assert render.format_range("2020-05", "2021-02", {"month": "numeric", "separator": "-"}) == "05/2020-02/2021"


def _project(**fields):
    from resume_tailor.content.data import Project

    return Project(id="p", name="Demo", **fields)


def test_a_range_with_matching_ends_prints_one_date():
    assert render.format_range("2025-03", "2025-03") == "Mar 2025"
    assert render.project_date(_project(start="2025-03", end="2025-03")) == "Mar 2025"
    assert render.project_date(_project(start="2025-03")) == "Mar 2025"


def test_project_dates_print_a_range_present_or_free_text():
    assert render.project_date(_project(start="2025-03", end="2025-05")) == "Mar 2025 - May 2025"
    assert render.project_date(_project(start="2025-03", end="Present")) == "Mar 2025 - Present"
    assert render.project_date(_project(date="Spring 2025")) == "Spring 2025"
    style = {"month": "full", "separator": " – "}
    assert render.project_date(_project(start="2025-03", end="2025-05"), style) == (
        "March 2025 – May 2025"
    )


def test_an_old_single_project_date_is_read_into_start_and_end():
    project = _project(date="2025-03")
    assert (project.start, project.end, project.date) == ("2025-03", "", "")
    project = _project(date="Mar 2025 - May 2025")
    assert (project.start, project.end) == ("2025-03", "2025-05")
    assert _project(date="Spring 2025").date == "Spring 2025"
