"""Keyword-search presets for the Sources page (position x level x industry).

- ``GET /api/apply/search-presets``: the choices (positions, levels, industries).
- ``GET /api/apply/search-presets/build``: the phrases and title filters for one
  choice, so the SPA never re-implements the phrase rules (`discovery/search_presets.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from resume_tailor.apply.discovery import search_presets

router = APIRouter()


class PresetChoice(BaseModel):
    id: str
    label: str


class IndustryChoice(PresetChoice):
    positions: list[str]


class SearchPresetChoices(BaseModel):
    positions: list[PresetChoice]
    levels: list[PresetChoice]
    industries: list[IndustryChoice]


class SearchPresetBuild(BaseModel):
    query: str
    include: list[str]
    exclude: list[str]


@router.get("/api/apply/search-presets", response_model=SearchPresetChoices)
def list_search_presets() -> SearchPresetChoices:
    return SearchPresetChoices(
        positions=[PresetChoice(id=p.id, label=p.label) for p in search_presets.POSITIONS],
        levels=[PresetChoice(id=lv.id, label=lv.label) for lv in search_presets.LEVELS],
        industries=[
            IndustryChoice(id=i.id, label=i.label, positions=list(i.positions))
            for i in search_presets.INDUSTRIES
        ],
    )


@router.get("/api/apply/search-presets/build", response_model=SearchPresetBuild)
def build_search_preset(
    positions: list[str] = Query(default_factory=list), level: str = Query(...)
) -> SearchPresetBuild:
    try:
        preset = search_presets.build_search(positions, level)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SearchPresetBuild(
        query=preset.query, include=list(preset.include), exclude=list(preset.exclude)
    )
