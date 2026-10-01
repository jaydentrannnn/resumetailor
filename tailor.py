"""Command-line entry point: job description in, tailored resume out.

    python tailor.py --jd jd.txt [--out output/tailored.docx] [--pages 1]

A shim so the CLI runs from a checkout without `pip install -e .`; the code lives in
`src/resume_tailor/cli/` (flags: `args.py`, the run: `run.py`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from resume_tailor.cli.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
