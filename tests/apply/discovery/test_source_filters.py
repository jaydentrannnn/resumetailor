"""Filters for every source: merging into a source, and hoisting shared words on load."""

from __future__ import annotations

from resume_tailor.apply.discovery import source_filters
from resume_tailor.web.schemas import ApplySettings, SourceConfig, SourceFilters


def _src(**kw) -> SourceConfig:
    return SourceConfig(id=kw.pop("id", "s"), kind="pipe_table", url="https://x/README.md", **kw)


def test_global_words_come_first_and_repeats_drop():
    merged = source_filters.with_global_filters(
        _src(include=["Associate", "analyst"], exclude=["ops"], locations=["Houston"]),
        SourceFilters(include=["Analyst"], exclude=["senior"], locations=["Remote"]),
    )
    assert merged.include == ["Analyst", "Associate"]
    assert merged.exclude == ["senior", "ops"]
    assert merged.locations == ["Remote", "Houston"]


def test_a_source_can_skip_the_global_keep_words_only():
    merged = source_filters.with_global_filters(
        _src(include=["quant"], ignore_global_include=True),
        SourceFilters(include=["analyst"], exclude=["senior"]),
    )
    assert merged.include == ["quant"]
    assert merged.exclude == ["senior"]


def test_no_global_words_leaves_the_source_as_is():
    src = _src(include=["analyst"])
    assert source_filters.with_global_filters(src, SourceFilters()).include == ["analyst"]


def _raw(*sources: dict) -> dict:
    return {
        "sources": [
            {"id": f"s{i}", "kind": "pipe_table", "url": "https://x/README.md", **src}
            for i, src in enumerate(sources)
        ]
    }


def _effective(settings: ApplySettings) -> list[tuple[set[str], ...]]:
    out = []
    for src in settings.sources:
        merged = source_filters.with_global_filters(src, settings.source_filters)
        out.append(tuple({w.lower() for w in getattr(merged, f)} for f in source_filters.FIELDS))
    return out


def test_old_settings_hoist_shared_words_without_changing_results():
    raw = _raw(
        {"include": ["analyst", "associate"], "exclude": ["Senior", "director"]},
        {"include": ["Analyst"], "exclude": ["senior"], "locations": ["NYC"]},
    )
    before = [
        tuple({w.lower() for w in src.get(f, [])} for f in source_filters.FIELDS)
        for src in raw["sources"]
    ]
    settings = ApplySettings.model_validate(raw)
    assert settings.source_filters.include == ["analyst"]
    assert settings.source_filters.exclude == ["Senior"]
    assert settings.source_filters.locations == []
    assert settings.sources[0].include == ["associate"]
    assert settings.sources[1].include == []
    assert _effective(settings) == before


def test_hoisting_needs_two_sources_and_runs_only_once():
    one = ApplySettings.model_validate(_raw({"exclude": ["senior"]}))
    assert one.sources[0].exclude == ["senior"]
    assert one.source_filters == SourceFilters()

    saved = _raw({"exclude": ["senior"]}, {"exclude": ["senior"]})
    saved["source_filters"] = {}
    kept = ApplySettings.model_validate(saved)
    assert [s.exclude for s in kept.sources] == [["senior"], ["senior"]]
    assert kept.source_filters == SourceFilters()
