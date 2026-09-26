"""Write the updater manifest (``latest.json``) for a tagged release.

The installed desktop app reads
``https://github.com/<repo>/releases/latest/download/latest.json`` (``plugins.updater``
in ``desktop/src-tauri/tauri.conf.json``). GitHub's ``latest`` skips drafts, so a
release reaches installed apps only once its draft is published.

Input is the folder the release workflow collects: each updater bundle next to its
``.sig`` (written by ``tauri build`` with ``bundle.createUpdaterArtifacts``):

- ``*-setup-windows-x64.exe`` → ``windows-x86_64`` / ``windows-x86_64-nsis``
- ``*-windows-x64.msi``       → ``windows-x86_64-msi``
- ``*.app.tar.gz``            → ``darwin-aarch64`` / ``darwin-aarch64-app``

The plain ``windows-x86_64`` key points at the NSIS installer: that is the one the
guide tells people to install, and the updater looks for ``<os>-<arch>-<installer>``
first, then ``<os>-<arch>``.

    python scripts/release_manifest.py --tag v0.2.0 --dir dist-installers \\
        --repo owner/name --notes-file notes.txt --out dist-installers/latest.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def platform_keys(file_name: str) -> list[str]:
    """Manifest keys a bundle serves, most specific first; [] for files it does not."""
    name = file_name.lower()
    if name.endswith(".exe") and "-setup" in name:
        return ["windows-x86_64-nsis", "windows-x86_64"]
    if name.endswith(".msi"):
        return ["windows-x86_64-msi"]
    if name.endswith(".app.tar.gz"):
        return ["darwin-aarch64-app", "darwin-aarch64"]
    return []


def build_manifest(
    tag: str, folder: Path, repo: str, notes: str, now: datetime | None = None
) -> dict:
    platforms: dict[str, dict[str, str]] = {}
    for sig in sorted(folder.glob("*.sig")):
        bundle = sig.with_name(sig.name[: -len(".sig")])
        if not bundle.is_file():
            raise SystemExit(f"{sig.name} has no bundle next to it")
        entry = {
            "signature": sig.read_text(encoding="utf-8").strip(),
            "url": f"https://github.com/{repo}/releases/download/{tag}/{bundle.name}",
        }
        for key in platform_keys(bundle.name):
            platforms.setdefault(key, entry)
    if "windows-x86_64" not in platforms:
        raise SystemExit(f"no signed Windows NSIS installer in {folder}")
    stamp = (now or datetime.now(UTC)).replace(microsecond=0)
    return {
        "version": tag.removeprefix("v"),
        "notes": notes.strip(),
        "pub_date": stamp.isoformat().replace("+00:00", "Z"),
        "platforms": platforms,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--tag", required=True, help="release tag, e.g. v0.2.0")
    parser.add_argument("--dir", type=Path, required=True, help="collected installers")
    parser.add_argument("--repo", required=True, help="GitHub owner/name")
    parser.add_argument("--notes-file", type=Path, help="release notes (plain text)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else ""
    manifest = build_manifest(args.tag, args.dir, args.repo, notes)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {manifest['version']} for {', '.join(sorted(manifest['platforms']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
