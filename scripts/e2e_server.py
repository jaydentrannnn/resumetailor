"""Start a throwaway ResumeTailor server for the browser e2e suite (`frontend/e2e/`).

Everything lives in a temporary folder, the model is the canned `fake_llm`, secrets
stay in memory and sign-in is off. The script seeds a synthetic resume, one installed
template and a few applications, then serves until it is killed. The page-fit steps
still need LibreOffice (or Word).

    python scripts/e2e_server.py --port 8777

Playwright's `webServer` runs this; it is not meant for real use.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _environment(root: Path) -> None:
    for name in ("data", "output", "templates"):
        (root / name).mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "RESUME_TAILOR_DATA_DIR": str(root / "data"),
            "RESUME_TAILOR_OUTPUT_DIR": str(root / "output"),
            "RESUME_TAILOR_TEMPLATES_DIR": str(root / "templates"),
            "RESUME_TAILOR_FAKE_LLM": "1",
            "RESUME_TAILOR_SECRETS_BACKEND": "memory",
            "RESUME_TAILOR_LOG_DIR": "off",
            "RESUME_TAILOR_AUTH": "off",
        }
    )


def _seed(base: str) -> None:
    import httpx

    sys.path.insert(0, str(ROOT))
    from resume_tailor.apply.answers import answer_memory
    from resume_tailor.apply.funnel import store
    from tests.fixtures import synthetic_resume
    from tests.web.helpers import _resume_upload_with_profile

    resume = synthetic_resume().model_dump(mode="json", by_alias=True)
    httpx.put(f"{base}/api/master-resume", json=resume, timeout=60).raise_for_status()
    upload, profile = _resume_upload_with_profile()
    httpx.post(
        f"{base}/api/template",
        data={"profile": profile, "label": "E2E template"},
        files={"file": ("resume.docx", upload, "application/octet-stream")},
        timeout=300,
    ).raise_for_status()
    httpx.put(f"{base}/api/onboarding", json={"completed": True}, timeout=30).raise_for_status()
    answer_memory.remember(
        "Which office would you prefer?", "New York", company="Acme Capital", ats="greenhouse"
    )
    app = store.Application
    for row in (
        app(
            source="simplify",
            source_job_id="e2e-review",
            company="Acme Capital",
            role="Summer Analyst",
            location="New York, NY",
            ats="greenhouse",
            status="awaiting_review",
            fill={
                "field_outcomes": [
                    {"label": "Salary expectations", "state": "unanswered", "required": True},
                ]
            },
        ),
        app(
            source="simplify",
            source_job_id="e2e-otp",
            company="Beta Bank",
            role="Analyst Intern",
            location="Remote",
            ats="greenhouse",
            status="awaiting_otp",
        ),
        app(
            source="simplify",
            source_job_id="e2e-queued",
            company="Gamma Labs",
            role="Data Intern",
            location="Boston, MA",
            ats="lever",
            status="screened_in",
        ),
    ):
        store.upsert(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8777)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="rt_e2e_"))
    _environment(root)
    sys.path.insert(0, str(ROOT / "src"))

    import httpx
    import uvicorn

    sys.path.insert(0, str(ROOT))
    from fastapi.responses import Response

    from resume_tailor.web.app import app
    from tests.pdf_fixtures import single_column_resume

    # Test-only: the synthetic PDF the import test uploads (no binary fixture in git).
    # Moved ahead of the SPA mount at "/", which would otherwise answer first.
    pdf = single_column_resume()
    app.add_api_route(
        "/e2e/resume.pdf", lambda: Response(pdf, media_type="application/pdf"), methods=["GET"]
    )
    app.router.routes.insert(0, app.router.routes.pop())

    # Test-only: job boards answer from memory (no network), so the watchlist test can
    # add a company. Any board name other than "acme" is "not found".
    from resume_tailor.apply.discovery import boards

    def _fake_board(ats: str, slug: str, **_kwargs):
        if slug.lower() != "acme":
            raise boards.BoardNotFound(slug)
        return [boards.BoardJob("1", "Summer Analyst", "New York, NY", "", "", "Acme Capital")]

    boards.list_board = _fake_board

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{args.port}"
    for _ in range(200):
        try:
            if httpx.get(f"{base}/api/config", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    _seed(base)
    # Playwright's readiness URL is the last seeded application, which 404s until now.
    print(f"e2e server ready at {base} (data in {root})", flush=True)
    thread.join()


if __name__ == "__main__":
    main()
