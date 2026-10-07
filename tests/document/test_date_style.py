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
