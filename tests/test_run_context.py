"""Concurrent run settings stay attached to their logical job."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from resume_tailor import config
from resume_tailor.content import style


def test_two_workspaces_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    monkeypatch.setattr(config, "TEMPLATES_ROOT", tmp_path / "templates")
    monkeypatch.setattr(config, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(config, "CACHE_ROOT", tmp_path / "cache")
    widths = {"alpha": 81, "beta": 117}
    for name, width in widths.items():
        path = config.workspace_paths(name)["CALIBRATION_DIR"] / f"{config.PDF_BACKEND}.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"chars_per_line": width, "lines_per_page": 45}))

    barrier = threading.Barrier(2)

    def read(name: str, profile: str):
        with config.use_context(config.context_for_workspace(name)):
            config.resolve(profile)
            style.activate(rewrite=name)
            barrier.wait(timeout=10)
            return (
                config.DATA_DIR,
                config.backend_for("rewrite").origin,
                config.CHARS_PER_LINE,
                style.active("rewrite"),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        alpha = pool.submit(read, "alpha", "claude")
        beta = pool.submit(read, "beta", "ollama")
        assert alpha.result(timeout=15) == (
            config.workspace_paths("alpha")["DATA_DIR"], "anthropic", 81, "alpha"
        )
        assert beta.result(timeout=15) == (
            config.workspace_paths("beta")["DATA_DIR"], "ollama", 117, "beta"
        )


def test_context_copy_helpers_and_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    style.activate(rewrite="outside override")
    with config.use_context(config.context_for_workspace("copy")):
        assert style.active("rewrite") == style.DEFAULT_REWRITE_STYLE
        config.resolve("ollama")
        wrapped = config.run_in_context(lambda: (config.DATA_DIR, config.backend_for("score").origin))
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert config.submit_in_context(
                pool, lambda: (config.DATA_DIR, config.backend_for("score").origin)
            ).result() == (
                config.workspace_paths("copy")["DATA_DIR"], "ollama"
            )
        with config.pinned("claude"):
            assert config.backend_for("score").origin == "anthropic"
        assert config.backend_for("score").origin == "ollama"
    assert wrapped() == (config.workspace_paths("copy")["DATA_DIR"], "ollama")


def test_set_active_workspace_changes_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data")
    config.set_active_workspace("default")
    assert config.active_workspace_id() == "default"
    assert config.workspace_paths("default")["DATA_DIR"] == config.DATA_DIR
