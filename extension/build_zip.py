"""Package the extension as ``resumetailor-extension-<version>.zip`` for a release.

The zip holds only what the browser loads: no tests, node_modules, store material or
build scripts. ``--version`` (the release tag without its ``v``) is written into the
zipped manifest, so the extension and the app ship the same version; the repo's
manifest is left alone.

    python extension/build_zip.py --version 1.2.3 --out dist
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
EXCLUDED_DIRS = frozenset({"tests", "node_modules", "store"})
EXCLUDED_FILES = frozenset({"package.json", "package-lock.json", ".gitignore"})
#: Chrome's manifest version: one to four dot-separated integers.
_VERSION = re.compile(r"^\d+(\.\d+){0,3}$")


def included(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return (
        path.is_file()
        and not EXCLUDED_DIRS.intersection(relative.parts[:-1])
        and relative.name not in EXCLUDED_FILES
        and path.suffix != ".py"
    )


def build(out_dir: Path, version: str | None = None) -> Path:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    if version:
        if not _VERSION.match(version):
            raise SystemExit(f"not a browser-extension version: {version!r}")
        manifest["version"] = version
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"resumetailor-extension-{manifest['version']}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not included(path):
                continue
            name = path.relative_to(ROOT).as_posix()
            if name == "manifest.json":
                archive.writestr(name, json.dumps(manifest, indent=2) + "\n")
            else:
                archive.write(path, name)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=None, help="release version, e.g. 1.2.3")
    parser.add_argument("--out", type=Path, default=Path("dist-extension"))
    args = parser.parse_args()
    print(build(args.out, args.version))


if __name__ == "__main__":
    main()
