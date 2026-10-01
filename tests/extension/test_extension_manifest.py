"""The unpacked extension must be complete and narrowly permissioned."""

import json
import re
import struct
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2] / "extension"
REPO = Path(__file__).parents[2]


def _manifest() -> dict:
    return json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_files_and_permissions():
    manifest = _manifest()
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {
        "storage",
        "activeTab",
        "scripting",
        "contextMenus",
        "alarms",
        "notifications",
    }
    # debugger drives only the tab the user attaches, and is requested only when the
    # relay is turned on in the options page.
    assert manifest["optional_permissions"] == ["debugger"]
    assert "debugger" not in manifest["permissions"]
    assert set(manifest["host_permissions"]) == {"http://127.0.0.1/*", "http://localhost/*"}
    # LinkedIn/Indeed are asked for at runtime, never at install.
    assert set(manifest["optional_host_permissions"]) == {
        "https://www.linkedin.com/*",
        "https://*.indeed.com/*",
    }
    assert "content_scripts" not in manifest
    assert "<all_urls>" not in json.dumps(manifest)
    assert (ROOT / "lib" / "relay.js").is_file()
    referenced = [
        manifest["background"]["service_worker"],
        manifest["action"]["default_popup"],
        manifest["options_ui"]["page"],
        *manifest["action"]["default_icon"].values(),
        *manifest["icons"].values(),
    ]
    for name in referenced:
        assert (ROOT / name).is_file(), name
    for size, name in manifest["icons"].items():
        raw = (ROOT / name).read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", raw[16:24]) == (int(size), int(size))
    for page in (manifest["action"]["default_popup"], manifest["options_ui"]["page"]):
        html = (ROOT / page).read_text(encoding="utf-8")
        for name in re.findall(r'(?:src|href)="([^"#]+)"', html):
            assert (ROOT / name).is_file(), name
    for script in ROOT.glob("**/*.js"):
        if "node_modules" in script.parts or "tests" in script.parts:
            continue
        source = script.read_text(encoding="utf-8")
        for imported in re.findall(r'(?:from|import) "(\.[^"]+)"', source):
            assert script.parent.joinpath(imported).is_file(), f"{script.name}: {imported}"


def test_injected_files_exist():
    """Files named in chrome.scripting calls are plain strings the loader never checks."""
    for module, name in (("lib/capture.js", "EXTRACT_FILES"), ("lib/boards.js", "CONTENT_FILES")):
        source = (ROOT / module).read_text(encoding="utf-8")
        listed = re.search(rf"{name} = \[([^\]]+)\]", source)
        assert listed, name
        for path in re.findall(r'"([^"]+)"', listed.group(1)):
            assert (ROOT / path).is_file(), path


def test_capture_shortcut_command():
    commands = _manifest()["commands"]
    assert set(commands) == {"capture-page"}
    assert commands["capture-page"]["suggested_key"]["default"]
    assert '"capture-page"' in (ROOT / "background.js").read_text(encoding="utf-8")


def test_extension_version_matches_the_app():
    """Release builds stamp both from the tag; in the repo they must agree."""
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert _manifest()["version"] == project["project"]["version"]


def test_release_zip_holds_only_what_the_browser_loads(tmp_path):
    import importlib.util
    import zipfile

    spec = importlib.util.spec_from_file_location("build_zip", ROOT / "build_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = module.build(tmp_path, "2.3.4")
    assert target.name == "resumetailor-extension-2.3.4.zip"
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        stamped = json.loads(archive.read("manifest.json"))
    assert stamped["version"] == "2.3.4"
    assert _manifest()["version"] != "2.3.4"  # the repo copy is untouched
    for required in ("background.js", "content.js", "extract.js", "options.html", "lib/sites.js"):
        assert required in names, required
    assert not any(
        name.startswith(("tests/", "store/", "node_modules/")) or name.endswith(".py")
        for name in names
    )
    assert "package.json" not in names
    with __import__("pytest").raises(SystemExit):
        module.build(tmp_path, "v1.0")


def test_store_submission_material():
    store = ROOT / "store"
    for name in ("PRIVACY.md", "LISTING.md", "PERMISSIONS.md", "SUBMITTING.md"):
        assert (store / name).is_file(), name
    justified = (store / "PERMISSIONS.md").read_text(encoding="utf-8")
    manifest = _manifest()
    for permission in (
        *manifest["permissions"],
        *manifest["optional_permissions"],
        *manifest["host_permissions"],
        *manifest["optional_host_permissions"],
    ):
        assert f"`{permission}`" in justified, permission
