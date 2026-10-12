"""Where a posting is and how it is worked (on-site, hybrid, remote) — pure, no LLM.

`parse` reads a source's free-text location ("Toronto, ON | Remote in USA") into places;
`allowed` keeps a posting when any of its places passes the location policy: the work
types switched on, and (unless postings needing sponsorship are kept) a country the
applicant may work in. A posting with no location, or a remote one naming no country,
is kept by default: there is nothing to rule it out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from resume_tailor.apply.funnel import packet_profile_fields

WorkType = Literal["onsite", "hybrid", "remote", "unknown"]

_REMOTE = re.compile(r"\bremote\b|work from home|\bwfh\b|\banywhere\b|\bvirtual\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_ONSITE = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin[- ]person\b", re.I)
_PLACES = re.compile(r"\s*(?:\||;|\n)\s*")


@dataclass(frozen=True)
class Place:
    """One place a posting names: its countries (empty when none is named) and work type."""

    text: str
    countries: frozenset[str]
    work_type: WorkType


@dataclass(frozen=True)
class LocationPolicy:
    """Which postings to keep. Defaults keep everything (the filter is opt-in)."""

    onsite: bool = True
    hybrid: bool = True
    remote: bool = True
    #: Countries the applicant may work in; empty = any country.
    countries: frozenset[str] = field(default_factory=frozenset)
    #: Also keep postings in other countries (answered as needing sponsorship).
    other_countries: bool = True
    #: Keep a remote posting that names no country.
    keep_unknown_remote: bool = True


def _work_type(text: str) -> WorkType:
    if _HYBRID.search(text):
        return "hybrid"
    if _REMOTE.search(text):
        return "remote"
    if _ONSITE.search(text):
        return "onsite"
    return "unknown"


def parse(location: str) -> list[Place]:
    """Each " | " / ";"-separated place of ``location``, in order."""
    places = [part for part in _PLACES.split(location or "") if part.strip()]
    found = packet_profile_fields.location_countries(" | ".join(places))
    return [
        Place(text=text, countries=frozenset(countries), work_type=_work_type(text))
        for text, countries in zip(places, found, strict=False)
    ]


def _place_allowed(place: Place, policy: LocationPolicy) -> bool:
    kind = "onsite" if place.work_type == "unknown" else place.work_type
    if not getattr(policy, kind):
        return False
    if not place.countries:
        return policy.keep_unknown_remote if kind == "remote" else True
    if policy.other_countries or not policy.countries:
        return True
    return bool(place.countries & policy.countries)


def allowed(location: str, policy: LocationPolicy) -> bool:
    """Whether a posting at ``location`` passes ``policy`` (any of its places will do)."""
    places = parse(location)
    return not places or any(_place_allowed(place, policy) for place in places)


def policy_for(filters: object, source: object, authorized: list[str]) -> LocationPolicy:
    """The policy for one source: the global ``filters`` (a `SourceFilters`), the source's
    ``keep_unknown_remote``, and the profile's authorized countries when ``filters``
    names none."""
    work = getattr(filters, "work_types", None)
    countries = list(getattr(filters, "countries", None) or []) or authorized
    return LocationPolicy(
        onsite=getattr(work, "onsite", True),
        hybrid=getattr(work, "hybrid", True),
        remote=getattr(work, "remote", True),
        countries=frozenset(c for c in countries if c),
        other_countries=getattr(filters, "other_countries", True),
        keep_unknown_remote=getattr(source, "keep_unknown_remote", True),
    )
