"""`_FillEntry._recheck_platform`: a fill uses the handling of the platform it landed on,
and the stored ATS only moves from "other"/"unknown" to a name older apps can read."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resume_tailor.apply.ats import ats_fingerprint, ats_hints
from resume_tailor.apply.forms import fill_entry, wizards


def _run(ats: str, *, hints: dict | None = None):
    run = object.__new__(fill_entry._FillEntry)  # noqa: SLF001
    run.page = SimpleNamespace(url="https://careers.acme.com/apply")
    run.app = SimpleNamespace(ats=ats)
    run.pkt = SimpleNamespace(field_hints=hints or {})
    run.ats_name = ats
    run.is_workday = False
    run.is_smartrecruiters = False
    run.wizard = wizards.for_fill(ats)
    run.hints = dict(hints or {})
    run.landed_platform = ""
    run.progress = lambda _msg: None
    return run


@pytest.fixture
def landed(monkeypatch):
    def land(platform: str):
        monkeypatch.setattr(ats_fingerprint, "page_platform", lambda _page: platform)
    return land


def test_a_company_page_that_lands_on_icims_uses_icims(landed):
    landed("icims")
    run = _run("other")
    run._recheck_platform()  # noqa: SLF001
    assert (run.app.ats, run.ats_name, run.landed_platform) == ("icims", "icims", "icims")
    assert run.hints == ats_hints.hints_for("icims")
    assert type(run.wizard) is type(wizards.for_fill("icims"))


def test_landing_on_workday_switches_to_the_workday_flow(landed):
    landed("workday")
    run = _run("unknown")
    run._recheck_platform()  # noqa: SLF001
    assert run.is_workday and run.wizard is None and run.app.ats == "workday"


def test_a_known_stored_ats_is_kept_and_packet_hints_win(landed):
    landed("smartrecruiters")
    run = _run("lever", hints={"#x": "email"})
    run._recheck_platform()  # noqa: SLF001
    assert run.app.ats == "lever"  # only other/unknown is rewritten
    assert run.ats_name == "smartrecruiters" and run.is_smartrecruiters
    assert run.hints == {"#x": "email"}


@pytest.mark.parametrize("platform", ["eightfold", "avature", "other", ""])
def test_a_platform_older_apps_cannot_store_changes_only_diagnostics(landed, platform):
    landed(platform)
    run = _run("other")
    before = run.wizard
    run._recheck_platform()  # noqa: SLF001
    assert run.app.ats == "other" and run.wizard is before
    assert run.landed_platform == platform
