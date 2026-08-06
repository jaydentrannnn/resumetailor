"""Tests for calibration integrity.

A binary search that collapses to its own search bound, or a calibration file that
reached disk with implausible numbers, must never silently become
`config.CHARS_PER_LINE`/`LINES_PER_PAGE` — that happened once for real
(`chars_per_line=20`, measured against a profile-installed template whose Projects
heading did not literally read "PROJECTS") and capped every rewritten bullet at
15-35 characters for two days before anyone noticed.

No Word/LibreOffice: `calibrate._render_pages`/`_nonblank_lines` are stubbed so the
search and collapse-detection logic is verified without a real renderer, matching the
rest of the suite's no-network, no-Word convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from resume_tailor import calibrate, config
from resume_tailor.data import Bullet, Experience, ExperienceSection, MasterResume


def _resume() -> MasterResume:
    """A minimal valid resume. `calibrate._single_bullet_resume`/`_n_bullet_resume`
    graft their own controlled "Calibration Co" entry onto whatever sections `base`
    already has, so this fixture only needs to be valid, not realistic."""
    return MasterResume(
        contact={"name": "Test User", "email": "test@example.com"},
        sections=[
            ExperienceSection(
                id="experience",
                title="Experience",
                entries=[
                    Experience(
                        id="acme",
                        company="Acme",
                        title="Engineer",
                        start="2020-01",
                        end="2020-02",
                        bullets=[Bullet(id="b1", text="Did a thing.", tags=["x"])],
                    )
                ],
            )
        ],
    )


# ----------------------------------------------------------------------------------
# _check_not_collapsed / _check_in_band — pure, no I/O
# ----------------------------------------------------------------------------------


def test_check_not_collapsed_raises_on_low_bound():
    with pytest.raises(calibrate.CalibrationError, match="collapsed"):
        calibrate._check_not_collapsed(20, 20, 220, "CHARS_PER_LINE")


def test_check_not_collapsed_raises_on_high_bound():
    with pytest.raises(calibrate.CalibrationError, match="collapsed"):
        calibrate._check_not_collapsed(220, 20, 220, "CHARS_PER_LINE")


def test_check_not_collapsed_passes_for_an_interior_value():
    calibrate._check_not_collapsed(101, 20, 220, "CHARS_PER_LINE")  # must not raise


def test_check_in_band_raises_below_band():
    with pytest.raises(calibrate.CalibrationError, match="plausible range"):
        calibrate._check_in_band(10, (40, 200), "CHARS_PER_LINE")


def test_check_in_band_raises_above_band():
    with pytest.raises(calibrate.CalibrationError, match="plausible range"):
        calibrate._check_in_band(300, (40, 200), "CHARS_PER_LINE")


def test_check_in_band_passes_inside_band():
    calibrate._check_in_band(101, (40, 200), "CHARS_PER_LINE")  # must not raise


# ----------------------------------------------------------------------------------
# _static_heading_texts — what must be excluded before counting wrapped lines
# ----------------------------------------------------------------------------------


def test_static_heading_texts_with_no_profile_uses_legacy_literals(monkeypatch):
    monkeypatch.setattr(calibrate.template_profile, "load_profile", lambda: None)
    assert calibrate._static_heading_texts() == {
        "EDUCATION",
        "WORK EXPERIENCES",
        "PROJECTS",
        "SKILLS",
    }


def test_static_heading_texts_uses_the_profiles_own_heading_text(monkeypatch):
    """A fixed-mode profile whose Projects heading was uploaded as "Selected Projects"
    (not literally "PROJECTS") must have THAT text excluded — this is the exact
    mechanism that once collapsed a real search to its floor."""
    profile = SimpleNamespace(
        section_mode="fixed",
        projects=SimpleNamespace(heading_text="Selected Projects"),
        skills=SimpleNamespace(heading_text="Technical Skills"),
    )
    monkeypatch.setattr(calibrate.template_profile, "load_profile", lambda: profile)
    assert calibrate._static_heading_texts() == {"SELECTED PROJECTS", "TECHNICAL SKILLS"}


def test_static_heading_texts_omits_a_kind_with_no_mapping(monkeypatch):
    profile = SimpleNamespace(section_mode="fixed", projects=None, skills=None)
    monkeypatch.setattr(calibrate.template_profile, "load_profile", lambda: profile)
    assert calibrate._static_heading_texts() == set()


def test_static_heading_texts_empty_under_generic_mode(monkeypatch):
    """Generic mode renders no heading at all for a zero-entry section (see
    `render.build_context`'s `if not rendered_entries: continue`), so there is nothing
    to filter regardless of what the headings are named."""
    profile = SimpleNamespace(
        section_mode="generic",
        projects=SimpleNamespace(heading_text="Selected Projects"),
        skills=SimpleNamespace(heading_text="Technical Skills"),
    )
    monkeypatch.setattr(calibrate.template_profile, "load_profile", lambda: profile)
    assert calibrate._static_heading_texts() == set()


# ----------------------------------------------------------------------------------
# _wrapped_line_count
# ----------------------------------------------------------------------------------


def test_wrapped_line_count_excludes_stop_titles(monkeypatch):
    monkeypatch.setattr(
        calibrate,
        "_nonblank_lines",
        lambda pdf_path, page_index: [
            "Calibration Co  Jan 2025 - Feb 2025",
            "Calibration Role",
            "a single wrapped line of bullet text",
            "PROJECTS",
            "SKILLS",
        ],
    )
    assert calibrate._wrapped_line_count(Path("unused.pdf"), {"PROJECTS", "SKILLS"}) == 1


def test_wrapped_line_count_counts_more_than_one_real_wrap(monkeypatch):
    monkeypatch.setattr(
        calibrate,
        "_nonblank_lines",
        lambda pdf_path, page_index: [
            "Calibration Role",
            "first wrapped line",
            "second wrapped line",
        ],
    )
    assert calibrate._wrapped_line_count(Path("unused.pdf"), set()) == 2


def test_wrapped_line_count_raises_when_probe_entry_is_not_on_the_page(monkeypatch):
    monkeypatch.setattr(
        calibrate, "_nonblank_lines", lambda pdf_path, page_index: ["Unrelated content"]
    )
    with pytest.raises(calibrate.CalibrationError, match="Calibration Role"):
        calibrate._wrapped_line_count(Path("unused.pdf"), set())


def test_wrapped_line_count_reproduces_the_custom_heading_bug(monkeypatch):
    """Without a correct stop-title filter, a "Selected Projects" heading (not
    literally "PROJECTS") would count as an extra wrapped line no matter what bullet
    length is tried — reproducing why the real search never converged."""
    monkeypatch.setattr(
        calibrate,
        "_nonblank_lines",
        lambda pdf_path, page_index: [
            "Calibration Role",
            "a one-line bullet",
            "Selected Projects",
        ],
    )
    # The old hardcoded filter ("PROJECTS", "SKILLS") would count 2 lines here and
    # never see "1", regardless of bullet length. The profile-derived filter fixes it.
    assert calibrate._wrapped_line_count(Path("unused.pdf"), {"SELECTED PROJECTS"}) == 1


# ----------------------------------------------------------------------------------
# calibrate_chars_per_line — the full search, with a fake renderer
# ----------------------------------------------------------------------------------


def _stub_renderer(monkeypatch, *, wraps_at: int, stop_title: str | None) -> None:
    """Simulate a renderer where the probe bullet wraps to a second line once its
    length exceeds `wraps_at`, optionally also emitting `stop_title` as a line on
    every page — reproducing, when the caller does not filter it, the exact way an
    unfiltered static heading collapses the search to its floor.

    Threads the bullet length from `_render_pages` to `_nonblank_lines` via the fake
    PDF path's name, since the two are independent monkeypatched functions with no
    other shared state.
    """

    def fake_render_pages(resume, stub):
        bullets = [b for s in resume.sections for e in s.entries for b in e.bullets]
        length = len(bullets[0].text) if bullets else 0
        return Path(f"fake_{length}_{stub}.pdf"), 1

    def fake_nonblank_lines(pdf_path, page_index):
        length = int(pdf_path.stem.split("_")[1])
        # The bullet's own first line always renders; a second line appears only once
        # its length exceeds `wraps_at`. Omitting the always-present first line here
        # would silently shift every count off by one against `_wrapped_line_count`'s
        # real contract (count everything *after* the "Calibration Role" line).
        lines = ["Calibration Role", "first line of bullet text"]
        if length > wraps_at:
            lines.append("a second, wrapped line")
        if stop_title:
            lines.append(stop_title)
        return lines

    monkeypatch.setattr(calibrate, "_render_pages", fake_render_pages)
    monkeypatch.setattr(calibrate, "_nonblank_lines", fake_nonblank_lines)


def test_calibrate_chars_per_line_converges_to_the_wrap_boundary(monkeypatch):
    _stub_renderer(monkeypatch, wraps_at=87, stop_title=None)
    monkeypatch.setattr(calibrate, "_static_heading_texts", lambda: set())
    assert calibrate.calibrate_chars_per_line(_resume()) == 87


def test_calibrate_chars_per_line_raises_when_a_static_heading_is_not_filtered(
    monkeypatch,
):
    """The historical bug, reproduced end to end: a heading that always renders (a
    profile-installed "Selected Projects") is never excluded by an empty filter, so
    every candidate looks wrapped and the search collapses to its floor — which must
    now raise instead of silently returning 20."""
    _stub_renderer(monkeypatch, wraps_at=87, stop_title="Selected Projects")
    monkeypatch.setattr(calibrate, "_static_heading_texts", lambda: set())  # wrong filter
    with pytest.raises(calibrate.CalibrationError, match="collapsed"):
        calibrate.calibrate_chars_per_line(_resume())


def test_calibrate_chars_per_line_converges_when_the_heading_is_correctly_filtered(
    monkeypatch,
):
    """Same scenario, but with the heading correctly named in the filter — the fix
    `_static_heading_texts` provides."""
    _stub_renderer(monkeypatch, wraps_at=87, stop_title="Selected Projects")
    monkeypatch.setattr(
        calibrate, "_static_heading_texts", lambda: {"SELECTED PROJECTS"}
    )
    assert calibrate.calibrate_chars_per_line(_resume()) == 87


def test_calibrate_chars_per_line_raises_on_an_out_of_band_result(monkeypatch):
    """A wrap boundary the search legitimately finds (inside its own [20, 220] search
    range, so `_check_not_collapsed` alone would not catch it) but which is absurd for
    any real resume template must still be rejected rather than written."""
    _stub_renderer(monkeypatch, wraps_at=25, stop_title=None)  # below the (40, 200) band
    monkeypatch.setattr(calibrate, "_static_heading_texts", lambda: set())
    with pytest.raises(calibrate.CalibrationError, match="plausible range"):
        calibrate.calibrate_chars_per_line(_resume())


# ----------------------------------------------------------------------------------
# config._load_calibration — the on-disk side of the same guard
# ----------------------------------------------------------------------------------


def test_load_calibration_falls_back_when_no_file_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    chars, lines, source, rejection = config._load_calibration("word")
    assert (chars, lines, source, rejection) == (
        config._FALLBACK_CHARS_PER_LINE,
        config._FALLBACK_LINES_PER_PAGE,
        "fallback",
        None,
    )


def test_load_calibration_rejects_the_exact_historical_bad_value(tmp_path, monkeypatch):
    """Pins the real incident: chars_per_line=20 must fall back, named, not load."""
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    (tmp_path / "word.json").write_text(
        json.dumps({"chars_per_line": 20, "lines_per_page": 60})
    )
    chars, lines, source, rejection = config._load_calibration("word")
    assert chars == config._FALLBACK_CHARS_PER_LINE
    assert lines == config._FALLBACK_LINES_PER_PAGE
    assert source == "fallback"
    assert rejection is not None
    assert "chars_per_line=20" in rejection


def test_load_calibration_rejects_an_out_of_band_lines_per_page_too(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    (tmp_path / "word.json").write_text(
        json.dumps({"chars_per_line": 101, "lines_per_page": 5})
    )
    chars, lines, source, rejection = config._load_calibration("word")
    assert source == "fallback"
    assert rejection is not None


def test_load_calibration_loads_an_in_band_file_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    path = tmp_path / "word.json"
    path.write_text(json.dumps({"chars_per_line": 101, "lines_per_page": 52}))
    chars, lines, source, rejection = config._load_calibration("word")
    assert (chars, lines) == (101, 52)
    assert source == str(path)
    assert rejection is None


# ----------------------------------------------------------------------------------
# run() — a hard-failing self-check must prevent write_calibration entirely
# ----------------------------------------------------------------------------------


def test_run_never_writes_when_the_boundary_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    (tmp_path / "main_template.docx").touch()
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path / "calibration")
    monkeypatch.setattr(calibrate.data, "load", lambda: _resume())
    monkeypatch.setattr(calibrate, "calibrate_chars_per_line", lambda base: 101)
    monkeypatch.setattr(
        calibrate,
        "verify_chars_per_line_boundary",
        lambda base, chars_per_line: (_ for _ in ()).throw(
            calibrate.CalibrationError("boundary check failed")
        ),
    )
    written: list[Path] = []
    monkeypatch.setattr(
        calibrate,
        "write_calibration",
        lambda *a, **kw: written.append(Path("should-not-be-called")),
    )

    with pytest.raises(calibrate.CalibrationError, match="boundary check failed"):
        calibrate.run(verify_anchors=False)

    assert written == []
    assert not (tmp_path / "calibration").exists()
