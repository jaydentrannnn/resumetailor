"""The unpacked extension must be complete and narrowly permissioned."""

import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).parents[1] / "extension"


def test_manifest_files_and_permissions():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {
        "storage",
        "activeTab",
        "scripting",
        "contextMenus",
        "alarms",
        "debugger",
    }
    assert set(manifest["host_permissions"]) == {"http://127.0.0.1/*", "http://localhost/*"}
    assert "<all_urls>" not in json.dumps(manifest)
    # X3 relay GO: debugger is needed only to drive the tab the user selects.
    assert (ROOT / "lib" / "relay.js").is_file()
    referenced = [
        manifest["background"]["service_worker"],
        manifest["action"]["default_popup"],
        manifest["action"]["default_icon"],
        *manifest["icons"].values(),
    ]
    for name in referenced:
        assert (ROOT / name).is_file(), name
    for size, name in manifest["icons"].items():
        raw = (ROOT / name).read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", raw[16:24]) == (int(size), int(size))
    assert (ROOT / "extract.js").is_file()
    popup = (ROOT / manifest["action"]["default_popup"]).read_text(encoding="utf-8")
    for name in re.findall(r'(?:src|href)="([^"]+)"', popup):
        assert (ROOT / name).is_file(), name
    for script in (
        "background.js", "popup.js", "lib/api.js", "lib/capture.js", "lib/workflow.js", "lib/relay.js",
    ):
        source = (ROOT / script).read_text(encoding="utf-8")
        for imported in re.findall(r'from "([^"]+)"', source):
            assert (ROOT / script).parent.joinpath(imported).is_file(), imported
