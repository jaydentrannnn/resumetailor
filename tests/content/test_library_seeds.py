"""Tests for the built-in vocabulary dictionary in `library_seeds/dictionary.json`.

The dictionary is the five former packs merged; these pin its structural invariants
(no chains, no double-claimed alias or verb) and the specific spelling/verb claims the
packs were grounded in — now true by default, with nothing to enable.
"""

from __future__ import annotations

import collections

from resume_tailor import config, library_seeds
from resume_tailor.content import libraries
from resume_tailor.pipeline import bullet_checks


def test_no_alias_is_also_a_term():
    terms = set(library_seeds.load()["terms"])
    assert not terms & set(library_seeds.builtin_aliases())


def test_no_alias_or_verb_is_claimed_twice():
    seed = library_seeds.load()
    aliases = collections.Counter(a for al in seed["terms"].values() for a in al)
    verbs = collections.Counter(v for vs in seed["verb_families"].values() for v in vs)
    assert [a for a, n in aliases.items() if n > 1] == []
    assert [v for v, n in verbs.items() if n > 1] == []


def test_the_default_dictionary_composes_without_diagnostics():
    assert libraries.resolve_effective().diagnostics == []


def test_ambiguous_abbreviations_are_not_aliases():
    """"IB"/"AP" mean International Baccalaureate / Advanced Placement on a student
    resume as often as investment banking / accounts payable; "mrr" and "10k" were
    dropped in the merge for the same cross-field reason."""
    assert not {"ib", "ap", "ar", "gpa", "mrr", "10k"} & set(library_seeds.builtin_aliases())


def test_former_pack_spellings_canonicalise_by_default():
    expected = {
        "py": "python",
        "k8s": "kubernetes",
        "DCF": "discounted cash flow",
        "M&A": "mergers and acquisitions",
        "Pivot Tables": "excel",
        "CapIQ": "capital iq",
        "US GAAP": "gaap",
        "A/P": "accounts payable",
        "SOX": "sarbanes-oxley",
        "GA4": "google analytics",
        "PPC": "paid search",
        "6 Sigma": "six sigma",
        "google workspace": "google drive suite",
        "ms office": "microsoft 365",
        "kpis": "kpi",
        "GTM": "go-to-market",
    }
    for raw, canonical in expected.items():
        assert config.canonical_tag(raw) == canonical, raw
    # The platform and the document are different things.
    assert config.canonical_tag("pitch book") == "pitch book"


def test_resume_openers_are_classified_by_default():
    assert config.verb_family("recruited") == "recruit"
    assert config.verb_family("received") == "gained"
    assert config.verb_family("collaborated") == "collaborate"
    assert config.verb_family("tracked") == "track"
    assert config.verb_family("forecasted") == "analyse"
    assert config.verb_family("grew") == config.verb_family("increased") == "improve"


def test_exact_duplicate_verb_repeats_are_caught_by_the_word_itself():
    texts = {
        "b7": "Collaborated with peers and Deloitte consultants to solve a case",
        "b12": "Collaborated on the planning and execution of the Heartbeat Bazaar",
    }
    collisions = bullet_checks.verb_collisions(texts)
    assert "b12" in collisions and "collaborated" in collisions["b12"]


def test_a_near_synonym_cluster_is_caught():
    texts = {
        "a": "Collaborated with the audit team on quarterly review.",
        "b": "Consulted with department heads on budget allocation.",
        "c": "Liaised with external vendors on contract terms.",
    }
    assert "c" in bullet_checks.verb_collisions(texts)


def test_weak_verbs_are_out_of_every_family():
    for weak in ("handled", "addressed", "supported", "selected", "reviewed", "communicated"):
        assert config.verb_family(weak) is None, weak
    for weak in config.WEAK_OPENERS:
        assert config.verb_family(weak) is None, weak


def test_a_weak_opener_is_re_voiced_even_when_it_is_the_only_bullet():
    collisions = bullet_checks.verb_collisions({"a": "Assisted senior bankers with 12 pitch books."})
    assert set(collisions) == {"a"}


def test_a_page_can_open_with_four_leadership_and_teamwork_verbs():
    """People-facing verbs are split across families so the two-per-family cap doesn't
    hold a page to two leadership or teamwork openers."""
    texts = {
        "a": "Led a 3-person hackathon team",
        "b": "Mentored students on core topics",
        "c": "Coordinated events and school tours",
        "d": "Partnered with Support Operations",
    }
    assert bullet_checks.verb_collisions(texts) == {}
