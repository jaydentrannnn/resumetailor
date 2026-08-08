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


# ----------------------------------------------------------------------------------
# check_render_anchors — pure decision logic, no renderer: baseline / match / drift /
# rebaseline / silent re-baseline on a legitimate resume or template change
# ----------------------------------------------------------------------------------


def _anchor_block(
    *,
    resume_sha: str = "resume-r1",
    template_sha: str = "template-t1",
    bullet_count: int = 25,
    subset_bullet_count: int = 12,
    full_pages: int = 2,
    subset_pages: int = 1,
) -> dict:
    return {
        "resume_sha256": resume_sha,
        "template_sha256": template_sha,
        "bullet_count": bullet_count,
        "subset_bullet_count": subset_bullet_count,
        "full_pages": full_pages,
        "subset_pages": subset_pages,
    }


def test_first_run_records_a_baseline_without_warning():
    measured = _anchor_block()
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=None, rebaseline=False
    )
    assert anchors == measured
    assert warning is None
    assert "recorded" in log_line


def test_matching_baseline_passes():
    previous = _anchor_block()
    measured = _anchor_block()
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=False
    )
    assert anchors == measured
    assert warning is None
    assert log_line.strip() == "anchor checks OK"


def test_drift_warns_and_keeps_the_old_baseline():
    """Same resume+template (matching fingerprints), but the page count changed — a
    real regression. The old baseline must survive on disk, not be silently
    overwritten by the drifted measurement."""
    previous = _anchor_block(full_pages=2)
    measured = _anchor_block(full_pages=3)
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=False
    )
    assert anchors == previous
    assert warning is not None
    assert "3" in warning and "2" in warning
    assert "--rebaseline" in warning
    assert "warning" in log_line


def test_drift_warning_covers_subset_page_count_too():
    previous = _anchor_block(subset_pages=1)
    measured = _anchor_block(subset_pages=2)
    _, _, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=False
    )
    assert warning is not None
    assert "subset" in warning


def test_rebaseline_adopts_the_new_measurement():
    previous = _anchor_block(full_pages=2)
    measured = _anchor_block(full_pages=3)
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=True
    )
    assert anchors == measured
    assert warning is None
    assert "updated" in log_line


def test_a_resume_edit_rebaselines_silently():
    """A different resume fingerprint legitimately changes the expected page count —
    this must never look like drift, even though `full_pages` also differs."""
    previous = _anchor_block(resume_sha="resume-r1", full_pages=2)
    measured = _anchor_block(resume_sha="resume-r2", full_pages=3)
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=False
    )
    assert anchors == measured
    assert warning is None
    assert "recorded" in log_line


def test_a_template_rebuild_rebaselines_silently():
    previous = _anchor_block(template_sha="template-t1", full_pages=2)
    measured = _anchor_block(template_sha="template-t2", full_pages=3)
    anchors, log_line, warning = calibrate.check_render_anchors(
        measured, previous=previous, rebaseline=False
    )
    assert anchors == measured
    assert warning is None
    assert "recorded" in log_line


# ----------------------------------------------------------------------------------
# measure_anchors — scale-free subset selection + fingerprints, renderer stubbed
# ----------------------------------------------------------------------------------


def _multi_bullet_resume() -> MasterResume:
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
                        bullets=[
                            Bullet(id="b1", text="One.", tags=["x"]),
                            Bullet(id="b2", text="Two.", tags=["x"]),
                            Bullet(id="b3", text="Three.", tags=["x"]),
                        ],
                    )
                ],
            )
        ],
    )


def test_measure_anchors_subset_is_half_the_bullets(tmp_path, monkeypatch):
    template_path = tmp_path / "main_template.docx"
    template_path.write_bytes(b"fake template bytes")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", template_path)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calibrate, "_render_pages", lambda resume, stub: (tmp_path / "full.pdf", 2))

    captured_bullets: dict[str, str] = {}

    def fake_render(resume, *, bullets=None, out=None, **kw):
        captured_bullets.update(bullets or {})
        return out

    monkeypatch.setattr(calibrate.render, "render", fake_render)
    monkeypatch.setattr(calibrate.render, "to_pdf", lambda out: tmp_path / "subset.pdf")
    monkeypatch.setattr(calibrate.render, "page_count", lambda pdf: 1)

    result = calibrate.measure_anchors(_multi_bullet_resume())

    assert result["bullet_count"] == 3
    assert result["subset_bullet_count"] == 1  # max(1, 3 // 2)
    assert set(captured_bullets) == {"b1"}
    assert result["full_pages"] == 2
    assert result["subset_pages"] == 1
    assert len(result["resume_sha256"]) == 16
    assert len(result["template_sha256"]) == 16


def test_resume_fingerprint_changes_with_content():
    a = calibrate._resume_fingerprint(_resume())
    edited = _resume()
    edited.contact.name = "Someone Else"
    b = calibrate._resume_fingerprint(edited)
    assert a != b


def test_template_fingerprint_changes_with_bytes(tmp_path, monkeypatch):
    path = tmp_path / "main_template.docx"
    path.write_bytes(b"version one")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", path)
    a = calibrate._template_fingerprint()
    path.write_bytes(b"version two")
    b = calibrate._template_fingerprint()
    assert a != b


# ----------------------------------------------------------------------------------
# write_calibration / _load_previous_anchors — file shape, backwards compatible
# ----------------------------------------------------------------------------------


def test_write_calibration_without_anchors_matches_the_old_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    path = calibrate.write_calibration(101, 52)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {"backend", "chars_per_line", "lines_per_page", "measured_at", "template"}


def test_write_calibration_with_anchors_includes_the_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    anchors = _anchor_block()
    path = calibrate.write_calibration(101, 52, anchors)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["anchors"] == anchors


def test_anchors_key_is_ignored_by_the_config_loader(tmp_path, monkeypatch):
    """A calibration file carrying the new `anchors` block still loads through
    `config._load_calibration` exactly as before — the loader only ever reads
    `chars_per_line`/`lines_per_page`."""
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    path = tmp_path / "word.json"
    path.write_text(
        json.dumps(
            {
                "chars_per_line": 101,
                "lines_per_page": 52,
                "anchors": _anchor_block(),
            }
        )
    )
    chars, lines, source, rejection = config._load_calibration("word")
    assert (chars, lines) == (101, 52)
    assert source == str(path)
    assert rejection is None


def test_load_previous_anchors_returns_none_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    assert calibrate._load_previous_anchors() is None


def test_load_previous_anchors_returns_none_for_a_pre_anchors_file(tmp_path, monkeypatch):
    """The file shape from before this feature existed (no `anchors` key at all) must
    read as "no baseline yet", not raise."""
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    (tmp_path / "word.json").write_text(json.dumps({"chars_per_line": 101, "lines_per_page": 52}))
    assert calibrate._load_previous_anchors() is None


def test_load_previous_anchors_reads_the_anchors_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path)
    monkeypatch.setattr(config, "PDF_BACKEND", "word")
    anchors = _anchor_block()
    (tmp_path / "word.json").write_text(
        json.dumps({"chars_per_line": 101, "lines_per_page": 52, "anchors": anchors})
    )
    assert calibrate._load_previous_anchors() == anchors


# ----------------------------------------------------------------------------------
# run() — the anchor step end to end: preserves an existing baseline when the step is
# skipped, never lets a drift warning block the write
# ----------------------------------------------------------------------------------


def _stub_run_prerequisites(monkeypatch, tmp_path):
    """Everything `run()` needs before the anchor step, stubbed so only the anchor
    machinery is under test."""
    monkeypatch.setattr(config, "DEFAULT_TEMPLATE_PATH", tmp_path / "main_template.docx")
    (tmp_path / "main_template.docx").write_bytes(b"template bytes")
    monkeypatch.setattr(config, "CALIBRATION_DIR", tmp_path / "calibration")
    monkeypatch.setattr(calibrate.data, "load", lambda: _resume())
    monkeypatch.setattr(calibrate, "calibrate_chars_per_line", lambda base: 101)
    monkeypatch.setattr(calibrate, "verify_chars_per_line_boundary", lambda base, chars_per_line: None)
    monkeypatch.setattr(calibrate, "calibrate_lines_per_page", lambda base, chars_per_line: 52)


def test_run_skipping_the_anchor_step_preserves_the_existing_baseline(tmp_path, monkeypatch):
    _stub_run_prerequisites(monkeypatch, tmp_path)
    calibration_dir = tmp_path / "calibration"
    calibration_dir.mkdir(parents=True)
    existing_anchors = _anchor_block()
    (calibration_dir / f"{config.PDF_BACKEND}.json").write_text(
        json.dumps({"chars_per_line": 90, "lines_per_page": 40, "anchors": existing_anchors})
    )

    result = calibrate.run(verify_anchors=False)

    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert payload["anchors"] == existing_anchors
    assert result.warnings is None


def test_run_anchor_step_failure_preserves_the_existing_baseline_and_warns(tmp_path, monkeypatch):
    _stub_run_prerequisites(monkeypatch, tmp_path)
    calibration_dir = tmp_path / "calibration"
    calibration_dir.mkdir(parents=True)
    existing_anchors = _anchor_block()
    (calibration_dir / f"{config.PDF_BACKEND}.json").write_text(
        json.dumps({"chars_per_line": 90, "lines_per_page": 40, "anchors": existing_anchors})
    )
    monkeypatch.setattr(
        calibrate,
        "measure_anchors",
        lambda base: (_ for _ in ()).throw(RuntimeError("PDF conversion failed")),
    )

    result = calibrate.run(verify_anchors=True)

    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert payload["anchors"] == existing_anchors
    assert result.warnings is not None
    assert any("PDF conversion failed" in w for w in result.warnings)
