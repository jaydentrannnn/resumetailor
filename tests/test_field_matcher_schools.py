"""School aliases come from data (`apply/school_aliases.json`), not per-school code."""

from __future__ import annotations

import pytest

from resume_tailor.apply import controls, field_matcher


@pytest.mark.parametrize(
    ("value", "option"),
    [
        ("UCI", "University of California, Irvine"),
        ("University of California - Irvine", "UC Irvine"),
        ("UCLA", "University of California, Los Angeles"),
        ("SJSU", "San Jose State University"),
        ("Cal Poly SLO", "California Polytechnic State University, San Luis Obispo"),
        ("Georgia Tech", "Georgia Institute of Technology"),
    ],
)
def test_alias_matches_option(value: str, option: str) -> None:
    assert field_matcher.closest_option(["Some Other College", option], value, key="school") == option


def test_search_terms_include_campus_and_data_terms() -> None:
    terms = field_matcher.search_terms("school", "University of California - Irvine")
    assert "Irvine" in terms and "UC Irvine" in terms
    davis = field_matcher.search_terms("school", "University of California - Davis")
    assert "Davis" in davis


def test_unknown_school_uses_generic_rules() -> None:
    terms = field_matcher.search_terms("school", "Harvey Mudd College")
    assert terms[0] == "Harvey Mudd College"
    assert "Harvey Mudd" in terms
    assert controls._search_term("school", "Harvey Mudd College") == "Harvey Mudd College"


def test_short_term_for_known_school() -> None:
    assert controls._search_term("school", "UC Irvine") == "Irvine"
    assert controls._search_term("school", "University of California Irvine") == "Irvine"


def test_diacritics_normalise() -> None:
    assert field_matcher.normalize("Université de Montréal") == "universite de montreal"
