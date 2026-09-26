"""Release helpers: the updater manifest and the third-party notices."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manifest = _load("release_manifest")
notices = _load("third_party_notices")


def _bundle(folder: Path, name: str, signature: str) -> None:
    (folder / name).write_bytes(b"bundle")
    (folder / f"{name}.sig").write_text(signature + "\n", encoding="utf-8")


def test_manifest_maps_each_signed_bundle(tmp_path):
    _bundle(tmp_path, "ResumeTailor_0.2.0_x64-setup-windows-x64.exe", "SIG-NSIS")
    _bundle(tmp_path, "ResumeTailor_0.2.0_x64_en-US-windows-x64.msi", "SIG-MSI")
    _bundle(tmp_path, "ResumeTailor.app.tar.gz", "SIG-MAC")
    (tmp_path / "ResumeTailor_0.2.0_aarch64-macos-arm64.dmg").write_bytes(b"not updatable")

    result = manifest.build_manifest(
        "v0.2.0", tmp_path, "owner/repo", " Fixes. \n", now=datetime(2026, 9, 26, tzinfo=UTC)
    )

    assert result["version"] == "0.2.0"
    assert result["notes"] == "Fixes."
    assert result["pub_date"] == "2026-09-26T00:00:00Z"
    platforms = result["platforms"]
    assert set(platforms) == {
        "windows-x86_64",
        "windows-x86_64-nsis",
        "windows-x86_64-msi",
        "darwin-aarch64",
        "darwin-aarch64-app",
    }
    assert platforms["windows-x86_64"]["signature"] == "SIG-NSIS"
    assert platforms["windows-x86_64"]["url"] == (
        "https://github.com/owner/repo/releases/download/v0.2.0/"
        "ResumeTailor_0.2.0_x64-setup-windows-x64.exe"
    )
    assert platforms["windows-x86_64-msi"]["signature"] == "SIG-MSI"


def test_manifest_requires_a_signed_windows_installer(tmp_path):
    (tmp_path / "ResumeTailor_0.2.0_x64-setup-windows-x64.exe").write_bytes(b"unsigned")
    with pytest.raises(SystemExit, match="no signed Windows"):
        manifest.build_manifest("v0.2.0", tmp_path, "owner/repo", "")


def test_manifest_cli_writes_json(tmp_path):
    _bundle(tmp_path, "ResumeTailor_1.0.0_x64-setup-windows-x64.exe", "S")
    notes = tmp_path / "notes.txt"
    notes.write_text("Hello", encoding="utf-8")
    out = tmp_path / "latest.json"
    code = manifest.main(
        ["--tag", "v1.0.0", "--dir", str(tmp_path), "--repo", "o/r",
         "--notes-file", str(notes), "--out", str(out)]
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["notes"] == "Hello"


def test_locked_names_skip_other_platforms(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "# comment\n"
        "httpx==0.28.1\n"
        "uvicorn[standard]==0.35.0\n"
        "appscript==1.4.0 ; sys_platform == 'never-a-platform'\n"
        "    # via something\n",
        encoding="utf-8",
    )
    assert notices.locked_python_names(lock) == ["httpx", "uvicorn"]


def test_notices_list_bundled_licenses(tmp_path):
    out = tmp_path / "NOTICES.txt"
    assert notices.main(["--out", str(out), "--cargo-manifest", str(tmp_path / "none.toml")]) == 0
    text = out.read_text(encoding="utf-8")
    assert "MIT-licensed" in text
    # The copyleft-ish dependencies whose licenses require attribution.
    assert "docxtpl" in text and "LGPL" in text
    assert "certifi" in text
