"""Find's location policy: work types, countries, and remote postings with no country."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from resume_tailor.apply.discovery import posting_location as loc

US_ONLY = loc.LocationPolicy(countries=frozenset({"United States"}), other_countries=False)


@pytest.mark.parametrize(
    "location,countries,work_type",
    [
        ("Remote in USA", {"United States"}, "remote"),
        ("Vancouver, BC (Hybrid)", {"Canada"}, "hybrid"),
        ("Belfast, United Kingdom", {"United Kingdom"}, "unknown"),
        ("Remote", set(), "remote"),
        ("Austin, TX - On-site", {"United States"}, "onsite"),
    ],
)
def test_parse_reads_country_and_work_type(location, countries, work_type):
    [place] = loc.parse(location)
    assert (set(place.countries), place.work_type) == (countries, work_type)


def test_defaults_keep_every_posting():
    for location in ("Belfast, United Kingdom", "Remote", "", "Toronto, ON"):
        assert loc.allowed(location, loc.LocationPolicy())


def test_other_countries_are_dropped_only_when_switched_off():
    assert not loc.allowed("Belfast, United Kingdom", US_ONLY)
    assert not loc.allowed("Toronto, ON", US_ONLY)
    assert loc.allowed("Toronto, ON | New York, NY", US_ONLY)
    assert loc.allowed("Plymouth, Minnesota", US_ONLY)
    # No country named: nothing rules it out.
    assert loc.allowed("Remote", US_ONLY)
    assert loc.allowed("", US_ONLY)


def test_work_type_switches_and_unknown_remote():
    no_remote = loc.LocationPolicy(remote=False)
    assert not loc.allowed("Remote in USA", no_remote)
    assert loc.allowed("Remote in USA | Austin, TX", no_remote)
    assert not loc.allowed("Seattle, WA (Hybrid)", loc.LocationPolicy(hybrid=False))
    assert not loc.allowed("Remote", loc.LocationPolicy(keep_unknown_remote=False))
    assert loc.allowed("Remote in USA", loc.LocationPolicy(keep_unknown_remote=False))


def test_policy_for_falls_back_to_the_profiles_countries():
    filters = SimpleNamespace(
        work_types=SimpleNamespace(onsite=True, hybrid=False, remote=True),
        countries=[], other_countries=False,
    )
    policy = loc.policy_for(filters, SimpleNamespace(keep_unknown_remote=False), ["Vietnam"])
    assert policy == loc.LocationPolicy(
        hybrid=False, countries=frozenset({"Vietnam"}), other_countries=False,
        keep_unknown_remote=False,
    )


def test_find_drops_rows_outside_the_policy(monkeypatch):
    from resume_tailor.apply.discovery.source_rows import SourceRow
    from resume_tailor.apply.funnel import daily_batch
    from resume_tailor.web.schemas import ApplySettings, SourceConfig

    monkeypatch.setattr(daily_batch, "_authorized_countries", lambda: ["United States"])
    settings = ApplySettings.model_validate({"source_filters": {"other_countries": False}})
    src = SourceConfig(id="s", kind="ats_board", url="", categories=[], enabled=True)
    rows = [
        SourceRow(company="A", role="Analyst", location=place, age="1d")
        for place in ("Austin, TX", "Belfast, United Kingdom", "Remote")
    ]
    kept, dropped = daily_batch.by_location(rows, src, settings)
    assert [r.location for r in kept] == ["Austin, TX", "Remote"]
    assert dropped == 1
