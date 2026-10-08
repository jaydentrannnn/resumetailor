"""The curated catalog of job sources the Apply page offers ("Add source → Catalog").

The catalog is a JSON file (``catalog/sources.json``) bundled with the app and also
fetched from this repo's main branch, so new lists (and next year's README URLs) reach
installed apps without a release. The remote copy is cached under ``config.DATA_ROOT``
(shared by every profile) with its ETag and refreshed at most every `REFRESH_SECONDS`;
a network failure falls back to the cache, and a remote copy that fails validation or
declares a newer ``schema_version`` than this app understands is ignored in favour of
the cache or the bundled copy. Nothing here changes a profile's saved sources: the UI
offers an update when an entry's ``version`` moves past a source's ``catalog_version``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from resume_tailor import config
from resume_tailor.web.schemas import (
    SOURCE_LEVELS,
    SOURCE_TRACKS,
    SourceConfig,
    SourceField,
)

log = logging.getLogger(__name__)

#: The newest catalog layout this app reads; a remote file with a higher one is ignored.
SCHEMA_VERSION = 1
DEFAULT_CATALOG_URL = (
    "https://raw.githubusercontent.com/jaydentrannnn/resumetailor/main/"
    "src/resume_tailor/apply/discovery/catalog/sources.json"
)
#: How long a cached remote copy is used before the next network check.
REFRESH_SECONDS = 12 * 60 * 60
CACHE_FILENAME = "source_catalog_cache.json"

CatalogOrigin = Literal["remote", "cache", "bundled"]


class CatalogEntry(BaseModel):
    """One curated source; ``template`` is what gets copied into ``ApplySettings.sources``."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    fields: list[SourceField] = Field(min_length=1)
    levels: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    version: str = Field(min_length=1)
    template: SourceConfig

    @field_validator("levels", "tracks", mode="before")
    @classmethod
    def _known_tags_only(cls, value: Any, info: ValidationInfo) -> Any:
        """Drop tags this build does not know, so a newer catalog still loads."""
        known = SOURCE_LEVELS if info.field_name == "levels" else SOURCE_TRACKS
        if not isinstance(value, list):
            return value
        return [tag for tag in value if tag in known]

    @model_validator(mode="after")
    def _stamp_template(self) -> CatalogEntry:
        """The template always records which entry and version it came from."""
        self.template = self.template.model_copy(
            update={
                "catalog_id": self.id,
                "catalog_version": self.version,
                "name": self.template.name or self.name,
            }
        )
        return self


class SourceCatalog(BaseModel):
    """The catalog file: a layout version and its entries (ids unique)."""

    schema_version: int = Field(ge=1)
    entries: list[CatalogEntry]

    @model_validator(mode="after")
    def _unique_ids(self) -> SourceCatalog:
        ids = [entry.id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("catalog entry ids must be unique")
        return self


class CatalogResponse(SourceCatalog):
    """``GET /api/apply/catalog``: the catalog plus where this copy came from."""

    origin: CatalogOrigin


def catalog_url() -> str:
    """The remote catalog address (``RESUME_TAILOR_CATALOG_URL`` overrides it)."""
    return os.environ.get("RESUME_TAILOR_CATALOG_URL", "").strip() or DEFAULT_CATALOG_URL


def cache_path() -> Path:
    """Where the last good remote copy is kept (shared by all profiles)."""
    return config.DATA_ROOT / CACHE_FILENAME


@lru_cache(maxsize=1)
def bundled() -> SourceCatalog:
    """The catalog shipped with this build (always valid; a test guards it)."""
    raw = (
        resources.files("resume_tailor.apply.discovery")
        .joinpath("catalog", "sources.json")
        .read_text(encoding="utf-8")
    )
    return SourceCatalog.model_validate_json(raw)


def _parse(raw: Any) -> SourceCatalog | None:
    """A usable catalog from decoded JSON, or None (invalid, or too new for this app)."""
    try:
        catalog = SourceCatalog.model_validate(raw)
    except ValidationError as exc:
        log.warning("source catalog failed validation: %s", exc.error_count())
        return None
    if catalog.schema_version > SCHEMA_VERSION:
        log.info(
            "source catalog schema %s is newer than %s", catalog.schema_version, SCHEMA_VERSION
        )
        return None
    return catalog


def _read_cache() -> dict[str, Any] | None:
    """The cache record ``{etag, fetched_at, url, body}``, or None."""
    path = cache_path()
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) and "body" in record else None


def _write_cache(url: str, etag: str, body: Any, fetched_at: float) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"url": url, "etag": etag, "fetched_at": fetched_at, "body": body},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        log.warning("could not write the source catalog cache at %s", path)


def load_catalog(
    *, get: Any = None, now: float | None = None, force: bool = False
) -> CatalogResponse:
    """The newest usable catalog and where it came from.

    Order: a cache younger than `REFRESH_SECONDS` (unless ``force``); otherwise the
    remote file (a 304 re-validates the cache); on any failure the cache; and finally
    the bundled copy. A cache from a different URL is ignored.
    """
    getter = get or httpx.get
    current = time.time() if now is None else now
    url = catalog_url()
    record = _read_cache()
    if record is not None and record.get("url") != url:
        record = None
    cached = _parse(record["body"]) if record is not None else None
    if record is not None and cached is None:
        record = None

    fresh = (
        record is not None
        and not force
        and current - float(record.get("fetched_at") or 0) < REFRESH_SECONDS
    )
    if fresh and cached is not None:
        return CatalogResponse(**cached.model_dump(), origin="cache")

    headers = {"If-None-Match": record["etag"]} if record and record.get("etag") else {}
    try:
        response = getter(url, headers=headers, follow_redirects=True, timeout=10.0)
        if response.status_code == 304 and record is not None and cached is not None:
            _write_cache(url, str(record.get("etag") or ""), record["body"], current)
            return CatalogResponse(**cached.model_dump(), origin="cache")
        if response.status_code != 200:
            raise ValueError(f"catalog answered {response.status_code}")
        body = json.loads(response.text)
        remote = _parse(body)
        if remote is None:
            raise ValueError("remote catalog is invalid or too new")
        etag = response.headers.get("ETag") or response.headers.get("etag") or ""
        _write_cache(url, etag, body, current)
        return CatalogResponse(**remote.model_dump(), origin="remote")
    except Exception as exc:  # noqa: BLE001 - the bundled copy always works
        fallback = "cache" if cached else "bundled"
        log.info("source catalog fetch failed (%s); using %s", exc, fallback)
    if cached is not None:
        return CatalogResponse(**cached.model_dump(), origin="cache")
    return CatalogResponse(**bundled().model_dump(), origin="bundled")


def bundled_template(entry_id: str) -> SourceConfig:
    """A fresh copy of a bundled entry's template (the built-in defaults use these)."""
    for entry in bundled().entries:
        if entry.id == entry_id:
            return entry.template.model_copy(deep=True)
    raise KeyError(f"no catalog entry {entry_id!r}")
