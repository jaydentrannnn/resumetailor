"""Catalog and endpoint checks without Google, credentials or an SDK download."""

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
