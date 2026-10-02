"""Pre-run cost estimate (PF4): arithmetic only, never a model call."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resume_tailor import config
from resume_tailor.pipeline import estimate
from tests.fixtures import synthetic_resume


def test_price_lookup_prefers_the_longest_prefix_and_never_guesses():
    assert estimate.price_for("anthropic", "claude-haiku-4-5") == (1.0, 5.0)
    assert estimate.price_for("gemini", "gemini-2.5-flash-lite") == (0.10, 0.40)
    assert estimate.price_for("ollama", "anything") == (0.0, 0.0)
    assert estimate.price_for("anthropic", "some-future-model") is None


def test_estimate_counts_stages_and_prices_known_models():
    resume = synthetic_resume()
    with config.pinned("anthropic:claude-haiku-4-5"):
        full = estimate.estimate_run("x" * 4000, resume, extract_runs=1, cover_letter=True)
        lean = estimate.estimate_run(
            "x" * 4000, resume, extract_runs=1, facets=False, expand=False, skills=False
        )
    stages = [s["stage"] for s in full["stages"]]
    assert stages == ["extract", "score", "facets", "rewrite", "expand", "skills", "cover"]
    assert full["calls"] == 8  # rewrite counts two fit rounds
    assert full["usd"] is not None and full["usd"] > lean["usd"] > 0
    assert not full["local"]


def test_local_and_unknown_models(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://localhost:11434/v1")
    resume = synthetic_resume()
    with config.pinned("ollama:llama3"):
        local = estimate.estimate_run("jd", resume, extract_runs=3)
    assert local["local"] and local["usd"] == 0
    assert local["stages"][0]["calls"] == 3
    with config.pinned("anthropic:some-future-model"):
        assert estimate.estimate_run("jd", resume, extract_runs=1)["usd"] is None


def test_estimate_route(tmp_path, monkeypatch):
    import json

    from resume_tailor.web.app import app

    path = tmp_path / "master_resume.json"
    path.write_text(json.dumps(synthetic_resume().model_dump(mode="json", by_alias=True)), encoding="utf-8")
    monkeypatch.setattr(config, "MASTER_RESUME_PATH", path)
    with TestClient(app) as c:
        res = c.post(
            "/api/jobs/estimate",
            json={"jd_text": "Python role", "settings": {"model": "anthropic:claude-haiku-4-5"}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["stages"][0]["calls"] == 1


def test_ollama_cloud_is_a_subscription_not_free_local(monkeypatch):
    resume = synthetic_resume()
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "https://ollama.com/v1")
    with config.pinned("ollama"):
        cloud = estimate.estimate_run("jd", resume, extract_runs=1)
    assert cloud["billing"] == "subscription"
    assert not cloud["local"]
    assert cloud["calls"] > 0 and cloud["input_tokens"] > 0
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    with config.pinned("ollama"):
        here = estimate.estimate_run("jd", resume, extract_runs=1)
    assert here["billing"] == "local" and here["local"]
    with config.pinned("claude"):
        assert estimate.estimate_run("jd", resume, extract_runs=1)["billing"] == "per_token"


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:1234/v1", True),
        ("http://[::1]:11434", True),
        ("http://host.docker.internal:11434/v1", True),
        ("http://192.168.1.20:11434", True),
        ("http://mybox.local:11434", True),
        ("https://ollama.com/v1", False),
        ("https://api.example.com", False),
        ("", False),
        (None, False),
    ],
)
def test_is_local_url(url, local):
    assert config.is_local_url(url) is local
