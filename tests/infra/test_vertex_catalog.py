"""Catalog and endpoint checks without Google, credentials or an SDK download."""

import threading
import time
from types import SimpleNamespace

import pytest

from resume_tailor.infra import vertex_catalog


def test_curated_managed_catalog_uses_current_ids_and_excludes_deployment_models(monkeypatch):
    monkeypatch.setattr(vertex_catalog, "sdk", lambda: SimpleNamespace(
        model_cost={"vertex_ai/zai-org/glm-5.2-maas": {"supported_regions": ["global"]}},
        get_supported_openai_params=lambda **_kwargs: [],
    ))
    entries = {item["id"]: item for item in vertex_catalog.suggestions()}
    assert len(entries) == 22
    assert entries["gemini-4-argon"]["name"] == "Gemini 4 Argon"
    assert entries["claude-haiku-5-5"]["publisher"] == "Anthropic"
    assert entries["zai-org/glm-5.2-maas"]["locations"] == ["global"]
    assert not any("image" in model or "endpoints/" in model for model in entries)
    assert "Qwen/Qwen3.8-27B" not in entries


@pytest.mark.parametrize("location, host", [
    ("global", "aiplatform.googleapis.com"),
    ("us", "aiplatform.us.rep.googleapis.com"),
    ("eu", "aiplatform.eu.rep.googleapis.com"),
    ("us-east5", "us-east5-aiplatform.googleapis.com"),
])
def test_location_host_matches_google_endpoint(location, host):
    assert vertex_catalog.endpoint("test-project", location) == (
        f"https://{host}/v1/projects/test-project/locations/{location}"
    )


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-sonnet-5-5"])
def test_new_claude_regions_use_google_metadata_when_sdk_catalog_is_missing(monkeypatch, model):
    monkeypatch.setattr(vertex_catalog, "sdk", lambda: SimpleNamespace(
        model_cost={}, get_supported_openai_params=lambda **_kwargs: [],
    ))
    entry = next(item for item in vertex_catalog.suggestions() if item["id"] == model)
    assert entry["locations"] == ["global", "us", "eu"]
    for location in entry["locations"]:
        vertex_catalog.validate_location(f"vertex_ai/{model}", location)
    for location in ("us-east1", "us-west4"):
        with pytest.raises(ValueError, match="global, us, eu"):
            vertex_catalog.validate_location(model, location)


def test_other_models_keep_sdk_regions_and_unknown_models_allow_custom_locations(monkeypatch):
    monkeypatch.setattr(vertex_catalog, "sdk", lambda: SimpleNamespace(
        model_cost={"vertex_ai/gemini-2.5-pro": {"supported_regions": ["us-central1"]}},
        get_supported_openai_params=lambda **_kwargs: [],
    ))
    entry = next(item for item in vertex_catalog.suggestions() if item["id"] == "gemini-2.5-pro")
    assert entry["locations"] == ["us-central1"]
    vertex_catalog.validate_location("gemini-2.5-pro", "us-central1")
    with pytest.raises(ValueError, match="us-central1"):
        vertex_catalog.validate_location("gemini-2.5-pro", "global")
    vertex_catalog.validate_location("custom-model", "us-east1")


def test_the_sdk_is_imported_by_one_thread_at_a_time(monkeypatch):
    # Two first imports at once deadlocked in LiteLLM's circular imports (2026-10-30).
    inside, most = [0], [0]

    def load():
        inside[0] += 1
        most[0] = max(most[0], inside[0])
        time.sleep(0.05)
        inside[0] -= 1
        return "sdk"

    monkeypatch.setattr(vertex_catalog, "_load_sdk", load)
    threads = [threading.Thread(target=vertex_catalog.sdk) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert most[0] == 1
