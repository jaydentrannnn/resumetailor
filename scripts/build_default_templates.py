"""Write the built-in starter templates to a folder so you can inspect them.

The app never reads this output: it builds a default template in memory when a student
installs it (`web/template_ops.install_default`). This script runs the same steps
(baseline → analyze → `template_build`) and, with ``--pdf``, renders each template
filled with its own sample content. Use it to check a design change by eye.

    python scripts/build_default_templates.py --out build/default_templates --pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor.document import default_templates  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="Folder to write into.")
    parser.add_argument("--name", choices=default_templates.names(), action="append")
    parser.add_argument("--pdf", action="store_true", help="Also render a filled PDF.")
    args = parser.parse_args(argv)

    for name in args.name or default_templates.names():
        folder = args.out / name
        written = default_templates.write_bundle(name, folder, pdf=args.pdf)
        for path in written:
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
