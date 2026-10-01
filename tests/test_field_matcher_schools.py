"""School aliases come from data (`apply/school_aliases.json`), not per-school code."""

from __future__ import annotations

import pytest

from resume_tailor.apply.driver import controls
from resume_tailor.apply.forms import field_matcher


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


def test_a_school_listed_twice_with_different_punctuation_is_chosen():
    """American Century's School search (2026-09-28) listed "University of California,
    Irvine" and "University of California-Irvine"; both normalise alike, which was read
    as a tie and left School blank."""
    listed = ["Irvine Valley College", "University of California, Irvine", "University of California-Irvine"]
    assert field_matcher.closest_option(listed, "University of California, Irvine", key="school") == listed[1]
    assert field_matcher.closest_option(listed, "University of California-Irvine", key="school") == listed[2]
    # Neither spelling matches exactly: the same words, so the first spelling.
    assert field_matcher.closest_option(listed, "University of California Irvine", key="school") == listed[1]
    # Identical labels are still a tie.
    assert field_matcher.closest_option(["No", "No"], "No") is None
