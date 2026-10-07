"""Typed ``---`` / ``--`` become real dashes on import; hyphenated words stay."""

from resume_tailor.importing import import_common


def test_spaced_typed_dashes_become_real_dashes():
    assert import_common.normalize_dashes("Irvine --- Paul Merage") == "Irvine \u2014 Paul Merage"
    assert import_common.normalize_dashes("Jul 2026 -- Present") == "Jul 2026 \u2013 Present"


def test_hyphens_inside_words_and_ranges_are_untouched():
    for text in ("full-time", "2020--2022", "state-of-the-art", "a -b"):
        assert import_common.normalize_dashes(text) == text
