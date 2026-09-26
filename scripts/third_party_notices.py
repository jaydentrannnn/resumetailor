"""Write THIRD-PARTY-NOTICES.txt: every component the desktop installer bundles.

Three sources, each read from what is installed rather than a hand-kept list:

- **Python**: the packages pinned in ``requirements.lock`` (what PyInstaller freezes),
  from ``importlib.metadata`` in the running environment, with the license files their
  wheels ship.
- **Web UI**: the runtime (non-dev) packages in ``frontend/package-lock.json``, from
  ``frontend/node_modules``.
- **Desktop shell**: the Rust crates from ``cargo metadata`` (skipped with a note when
  cargo is not installed, unless ``--require-cargo``).

Identical license texts are printed once, with the components that use them, so the
hundreds of MIT/Apache crates do not repeat the same text hundreds of times.

    python scripts/third_party_notices.py --out THIRD-PARTY-NOTICES.txt
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LICENSE_NAME = re.compile(r"^(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)


@dataclass
class Component:
    group: str
    name: str
    version: str
    license: str
    texts: list[str] = field(default_factory=list)


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _marker_applies(marker: str) -> bool:
    """Whether an environment marker (``sys_platform == 'darwin'``) holds on this machine."""
    try:
        from packaging.markers import Marker
    except ImportError:
        return True
    return Marker(marker).evaluate()


def locked_python_names(lock: Path) -> list[str]:
    """Package names pinned in a pip lock file (``name==version`` lines) for this platform."""
    names = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        requirement, _, marker = line.partition(";")
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*==", requirement)
        if match and (not marker.strip() or _marker_applies(marker.strip())):
            names.append(match.group(1))
    return names


def _python_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    classifiers = [
        c.split("::")[-1].strip()
        for c in meta.get_all("Classifier") or []
        if c.startswith("License ::") and "OSI Approved" not in c.split("::")[-1]
    ]
    if classifiers:
        return "; ".join(classifiers)
    free_text = (meta.get("License") or "").strip()
    # Some packages paste the whole license into this field; keep only its first line.
    return free_text.splitlines()[0][:80] if free_text else "UNKNOWN"


def python_components(lock: Path) -> list[Component]:
    out = []
    for name in locked_python_names(lock):
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            out.append(Component("Python", name, "?", "not installed when notices were built"))
            continue
        texts = []
        for file in dist.files or []:
            if _LICENSE_NAME.match(Path(str(file)).name) and ".dist-info" in str(file):
                try:
                    texts.append(Path(dist.locate_file(file)).read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
        out.append(
            Component("Python", dist.metadata["Name"], dist.version, _python_license(dist), texts)
        )
    return out


def _license_texts(folder: Path) -> list[str]:
    texts = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            if path.is_file() and _LICENSE_NAME.match(path.name):
                try:
                    texts.append(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError):
                    continue
    return texts


def npm_components(frontend: Path) -> list[Component]:
    lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    out = []
    for key, entry in sorted(lock.get("packages", {}).items()):
        if not key or entry.get("dev") or entry.get("devOptional"):
            continue
        name = key.rsplit("node_modules/", 1)[-1]
        folder = frontend / key
        license_ = entry.get("license")
        manifest = folder / "package.json"
        if not license_ and manifest.is_file():
            license_ = json.loads(manifest.read_text(encoding="utf-8")).get("license")
        out.append(
            Component(
                "Web UI (npm)",
                name,
                entry.get("version", "?"),
                str(license_ or "UNKNOWN"),
                _license_texts(folder),
            )
        )
    return out


def cargo_components(manifest: Path) -> list[Component] | None:
    """Crates of the desktop shell, or None when cargo is not available."""
    cargo = shutil.which("cargo")
    if cargo is None or not manifest.is_file():
        return None
    result = subprocess.run(
        [cargo, "metadata", "--format-version", "1", "--manifest-path", str(manifest)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    members = set(data.get("workspace_members", []))
    out = []
    for package in sorted(data["packages"], key=lambda p: (p["name"], p["version"])):
        if package["id"] in members:
            continue
        out.append(
            Component(
                "Desktop shell (Rust)",
                package["name"],
                package["version"],
                package.get("license") or "UNKNOWN",
                _license_texts(Path(package["manifest_path"]).parent),
            )
        )
    return out


def render(components: list[Component], notes: list[str]) -> str:
    lines = [
        "ResumeTailor: third-party notices",
        "",
        "ResumeTailor itself is MIT-licensed (see LICENSE). It bundles the components",
        "below, each under its own license. Where a license text was shipped with the",
        "component it is reproduced at the end, once per distinct text.",
        "",
    ]
    lines += [f"Note: {note}" for note in notes]
    groups: dict[str, list[Component]] = {}
    for component in components:
        groups.setdefault(component.group, []).append(component)
    for group, members in groups.items():
        lines += ["", f"== {group} ({len(members)}) ==", ""]
        lines += [f"{c.name} {c.version}: {c.license}" for c in members]

    by_text: dict[str, list[str]] = {}
    for component in components:
        for text in component.texts:
            by_text.setdefault(text.strip(), []).append(f"{component.name} {component.version}")
    lines += ["", "== License texts ==", ""]
    for text, users in by_text.items():
        lines += ["-" * 78, "Used by: " + ", ".join(sorted(set(users))), "-" * 78, text, ""]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out", type=Path, default=ROOT / "THIRD-PARTY-NOTICES.txt")
    parser.add_argument("--lock", type=Path, default=ROOT / "requirements.lock")
    parser.add_argument("--frontend", type=Path, default=ROOT / "frontend")
    parser.add_argument(
        "--cargo-manifest", type=Path, default=ROOT / "desktop" / "src-tauri" / "Cargo.toml"
    )
    parser.add_argument(
        "--require-cargo", action="store_true", help="fail instead of skipping the Rust crates"
    )
    args = parser.parse_args(argv)

    notes: list[str] = []
    components = python_components(args.lock)
    if (args.frontend / "package-lock.json").is_file():
        components += npm_components(args.frontend)
    else:
        notes.append("frontend/package-lock.json not found; web UI packages not listed.")
    crates = cargo_components(args.cargo_manifest)
    if crates is None:
        if args.require_cargo:
            print("cargo or Cargo.toml not found (--require-cargo)", file=sys.stderr)
            return 1
        notes.append("cargo or Cargo.toml was not available; desktop shell crates not listed.")
    else:
        components += crates

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(components, notes), encoding="utf-8")
    print(f"wrote {args.out} ({len(components)} components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
