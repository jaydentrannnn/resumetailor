"""Tests for the fit loop.

No test here exercises a live API call or Word/COM — `rewrite_bullets` and the
`render` module are monkeypatched so the loop's selection/shorten/underflow logic is
verified in isolation, matching the rest of the suite's no-network convention.
"""

from __future__ import annotations

import pytest

from resume_tailor import config, fit as fit_mod
from resume_tailor.data import load
from resume_tailor.jd import JobRequirements, Keyword
from resume_tailor.rewrite import RewriteOutcome


def _requirements() -> JobRequirements:
    return JobRequirements(
        title="Software Engineer",
        seniority="entry",
        keywords=[Keyword(phrase="Python", canonical="python", importance="must_have")],
    )


def _identity_rewrite(
    bullets,
    requirements,
    *,
    char_budget,
    shorten_pct=0,
    repair_widows=True,
    repair_verbs=True,
    merge_groups=None,
    on_event=None,
):
    """Pass-through rewrite stub that ignores polish and merge knobs."""
    return RewriteOutcome({b.id: b.text for b in bullets})


def test_estimate_lines_scales_with_bullet_count():
    resume = load()
    empty = fit_mod.estimate_lines(resume, {})
    full = fit_mod.estimate_lines(resume, {b.id: b.text for b in resume.all_bullets()})
    assert full > empty


def test_estimate_lines_drops_entry_with_no_surviving_bullets():
    """An entry whose bullets were all dropped contributes nothing, mirroring build_context."""
    resume = load()
    one_job_bullets = {b.id: b.text for b in resume.experience[0].bullets}
    assert fit_mod.estimate_lines(resume, one_job_bullets) > fit_mod.estimate_lines(resume, {})


#: A measured line count that clears UNDERFLOW_THRESHOLD, so the loop stops rather than
#: growing the selection. Derived from config so it tracks a re-calibration.
_FULL_LINES = config.LINES_PER_PAGE
_SPARSE_LINES = int(config.LINES_PER_PAGE * config.UNDERFLOW_THRESHOLD) - 5


def test_fit_escalates_shorten_schedule_on_overflow(monkeypatch, tmp_path):
    resume = load()
    requirements = _requirements()

    calls: list[int] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Record shorten_pct so the overflow schedule can be asserted."""
        calls.append(shorten_pct)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    pages = iter([2, 2, 1])  # overflow, overflow, fits on the third attempt

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(
        fit_mod.render, "measure_detail", lambda *a, **k: (next(pages), _FULL_LINES)
    )
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert calls == [0, *config.SHORTEN_SCHEDULE[:2]]
    assert result.pages == 1
    assert result.iterations == 3


def test_fit_raises_after_max_attempts_without_truncating(monkeypatch, tmp_path):
    resume = load()
    requirements = _requirements()

    calls: list[int] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Record shorten_pct so exhausting MAX_FIT_ATTEMPTS can be asserted."""
        calls.append(shorten_pct)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (2, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    with pytest.raises(fit_mod.FitError, match="Could not fit"):
        fit_mod.fit(resume, requirements, target_pages=1)

    assert len(calls) == config.MAX_FIT_ATTEMPTS
    assert calls == [0, *config.SHORTEN_SCHEDULE[: config.MAX_FIT_ATTEMPTS - 1]]


def test_fit_restores_bullets_on_underflow(monkeypatch, tmp_path):
    """A sparse page must pull bullets back rather than shipping half-empty."""
    resume = load()
    requirements = _requirements()
    entries = fit_mod.choose_entries(resume, requirements)
    available = sum(len(e.bullets) for e in entries)
    initial_limit = fit_mod._initial_selection_size(resume, entries, requirements, target_pages=1)
    assert initial_limit < available, "test needs room to grow the selection"

    seen: dict[str, int] = {}

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Track selection size so underflow growth can be asserted."""
        seen["count"] = len(bullets)
        return _identity_rewrite(bullets, requirements, char_budget=char_budget, shorten_pct=shorten_pct)

    # Underfull while the selection is at its starting size; full once it has grown.
    def fake_measure(*a, **k):
        return (1, _SPARSE_LINES if seen["count"] <= initial_limit else _FULL_LINES)

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", fake_measure)
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.bullets_selected > initial_limit
    # Specifically no *underflow* warning — the point of the test is that growing worked.
    # A widow warning is unrelated here: this fake returns the master resume's own text
    # verbatim, and some source bullets happen to end on a near-empty line.
    assert not [w for w in result.warnings if "full" in w]


def test_fit_stops_growing_after_max_attempts_and_warns(monkeypatch, tmp_path):
    """Underflow is not fatal: return the fullest version reached, but say it is sparse."""
    resume = load()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _SPARSE_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.pages == 1
    assert any("full" in w for w in result.warnings)


def test_fit_honours_entry_caps_and_never_drops_a_chosen_entry(monkeypatch, tmp_path):
    """Entry count is a shape decision; the loop may trim bullets but not whole entries."""
    resume = load()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    result = fit_mod.fit(resume, requirements, target_pages=1, max_experience=3, max_projects=2)

    rendered_jobs = [e for e in resume.experience if any(b.id in result.bullets for b in e.bullets)]
    rendered_projects = [
        p for p in resume.projects if any(b.id in result.bullets for b in p.bullets)
    ]
    assert len(rendered_jobs) == 3
    assert len(rendered_projects) == 2


def test_semantic_table_reaches_entry_selection(monkeypatch, tmp_path):
    """The relevance table must actually steer which entries appear, not just be accepted."""
    resume = load()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(fit_mod.render, "measure_detail", lambda *a, **k: (1, _FULL_LINES))
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    # Pick a job that keyword ranking leaves out, and make it the most relevant thing on
    # the resume semantically.
    baseline = fit_mod.fit(resume, requirements, target_pages=1)
    excluded = next(
        e for e in resume.experience if not any(b.id in baseline.bullets for b in e.bullets)
    )
    table = {b.id: 10.0 for b in excluded.bullets}

    result = fit_mod.fit(resume, requirements, target_pages=1, semantic=table)

    assert any(b.id in result.bullets for b in excluded.bullets)
    assert result.semantic_used is True
    assert baseline.semantic_used is False


def test_fit_falls_back_to_budget_estimate_when_word_unavailable(monkeypatch, tmp_path):
    """render.measure_detail raising RuntimeError (no Word) must not crash the run."""
    resume = load()
    requirements = _requirements()

    monkeypatch.setattr(fit_mod, "rewrite_bullets", _identity_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")

    def fake_measure(*a, **k):
        raise RuntimeError("Word is not installed")

    monkeypatch.setattr(fit_mod.render, "measure_detail", fake_measure)
    monkeypatch.setattr(fit_mod, "estimate_lines", lambda resume, bullets: _FULL_LINES)

    result = fit_mod.fit(resume, requirements, target_pages=1)

    assert result.pages_are_estimated
    assert any("Word is not installed" in w for w in result.warnings)


def test_merge_proposals_wait_until_measured_overflow(monkeypatch, tmp_path):
    """With merge_bullets on, attempt 0 must not propose; overflow attempts may."""
    resume = load()
    requirements = _requirements()
    seen_groups: list[list] = []

    def fake_rewrite(
        bullets,
        requirements,
        *,
        char_budget,
        shorten_pct=0,
        repair_widows=True,
        repair_verbs=True,
        merge_groups=None,
        on_event=None,
    ):
        """Capture merge_groups passed on each rewrite attempt."""
        seen_groups.append(list(merge_groups or []))
        return RewriteOutcome({b.id: b.text for b in bullets})

    pages = iter([2, 1])  # first measure overflows, second fits

    monkeypatch.setattr(fit_mod, "rewrite_bullets", fake_rewrite)
    monkeypatch.setattr(fit_mod.render, "render", lambda *a, **k: tmp_path / "out.docx")
    monkeypatch.setattr(
        fit_mod.render, "measure_detail", lambda *a, **k: (next(pages), _FULL_LINES)
    )
    monkeypatch.setattr(fit_mod.render, "to_pdf", lambda *a, **k: tmp_path / "out.pdf")

    # Force a deterministic non-empty proposal after overflow so the gate is visible.
    sentinel = object()

    def fake_propose(*a, **k):
        """Return a sentinel group list whenever propose is reached."""
        return [sentinel]

    monkeypatch.setattr(fit_mod, "propose_merges", fake_propose)

    fit_mod.fit(resume, requirements, target_pages=1, merge_bullets=True)

    assert seen_groups[0] == [], "first draft must not merge"
    assert seen_groups[1] == [sentinel], "overflow attempt must be allowed to merge"
