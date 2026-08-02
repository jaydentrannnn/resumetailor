"""CLI wrapper: measure fit constants for the active tagged template.

    python scripts/calibrate.py

Logic lives in `resume_tailor.calibrate` so the Template tab can run the same path
after an upload without shelling out.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resume_tailor.calibrate import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
