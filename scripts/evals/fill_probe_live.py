"""`fill_probe.py live`, one target: the real fill with the made-up applicant, guarded.

Run by `fill_probe.py` in a child process whose environment already points every app path
at a throwaway sandbox and ``CHROME_CDP_URL`` at the probe's own Chrome.

    fill_probe_live.py <out_dir> <tag> <url> [ats]
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_form  # noqa: E402
import fill_probe_data as synth  # noqa: E402
import fill_probe_guard  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.apply.answers import answer, hybrid_resolver  # noqa: E402
from resume_tailor.apply.discovery import fetch_jd  # noqa: E402
from resume_tailor.apply.driver import browser  # noqa: E402
from resume_tailor.apply.forms import fill as fill_mod  # noqa: E402
from resume_tailor.apply.funnel import store, store_models  # noqa: E402
from resume_tailor.web.schemas import ApplySettings  # noqa: E402

OUT, TAG, URL = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
ATS = sys.argv[4] if len(sys.argv) > 4 else ""
AUDIT = fill_probe_guard.Audit(OUT / f"{TAG}.requests.jsonl")
CALLS: Counter[str] = Counter()
CLIENTS = [0]  # classifier client builds: one per model call
ASKED: list[dict[str, str]] = []  # controls the resolver put to the model (labels only)
_STEP = re.compile(r"scanning form step (\d+)")


def _app() -> store_models.Application:
    config.MASTER_RESUME_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.MASTER_RESUME_PATH.write_text(synth.RESUME.model_dump_json(indent=1), encoding="utf-8")
    job_id = f"probe-{TAG}"
    job_dir = config.OUTPUT_DIR / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    ats = ATS or fetch_jd.detect_ats(URL)
    (job_dir / "run.json").write_text(
        json.dumps(
            {
                "metadata": {
                    "ats": ats,
                    "posting_url": URL,
                    "company": "Probe",
                    "role": "Software Engineer Intern",
                },
                "report": {"title": "Software Engineer Intern"},
            }
        ),
        encoding="utf-8",
    )
    synth.write_pdf(job_dir / "tailored.pdf")
    (job_dir / "skills.json").write_text(json.dumps({"skills": synth.SKILLS}), encoding="utf-8")
    (job_dir / "jd.txt").write_text(
        "Software Engineer Intern. Summer 2027 internship.", encoding="utf-8"
    )
    app = store_models.Application(
        source="probe",
        source_job_id=job_id,
        company="Probe",
        role="Software Engineer Intern",
        location="United States",
        posting_url=URL,
        final_url=URL,
        ats=ats if ats in store_models.AtsKind.__args__ else "other",
        status="ready",
        job_id=job_id,
        canonical_key=f"probe:{TAG}",
    )
    store.upsert(app)
    return store.get(app.source_job_id)


_original_cdp = browser.cdp_browser


@contextlib.contextmanager
def _guarded_cdp():
    with _original_cdp() as connected:
        context = connected.contexts[0] if connected.contexts else connected.new_context()
        fill_probe_guard.install(context, AUDIT, synth.MARKERS, synth.ANSWER_MARKERS)
        yield connected


def _count(name, fn, *, via_client=False):
    """Count each call of ``fn``; with ``via_client``, only one that reached the model
    (the classifiers answer cached questions without a call)."""
    def wrapper(*args, **kwargs):
        before = CLIENTS[0]
        try:
            return fn(*args, **kwargs)
        finally:
            if not via_client or CLIENTS[0] > before:
                CALLS[name] += 1

    return wrapper


def _client_counted(fn):
    def wrapper(*args, **kwargs):
        CLIENTS[0] += 1
        return fn(*args, **kwargs)

    return wrapper


def _asked_recorded(fn):
    """Keep the label and type of each control put to the resolver's model, never its value."""
    def wrapper(self, to_ask, *args, **kwargs):
        ASKED.extend(
            {"label": str(f.get("label") or "")[:120], "type": str(f.get("type") or "")}
            for f in to_ask if isinstance(f, dict)
        )
        return fn(self, to_ask, *args, **kwargs)

    return wrapper


def _patch() -> None:
    browser.cdp_browser = _guarded_cdp
    fill_mod.browser.cdp_browser = _guarded_cdp
    answer._classify_client = _client_counted(answer._classify_client)
    answer.classify_questions = _count(
        "classify_questions", answer.classify_questions, via_client=True
    )
    answer.classify_notices = _count(
        "classify_notices", answer.classify_notices, via_client=True
    )
    answer.answer_question = _count("answer_question", answer.answer_question)
    hybrid_resolver._StepResolver._call_model = _count(
        "resolver", _asked_recorded(hybrid_resolver._StepResolver._call_model)
    )


def _settings() -> ApplySettings:
    path = Path(os.environ["LOCALAPPDATA"]) / "ResumeTailorData" / "data" / "ai_settings.json"
    raw = json.loads(path.read_text(encoding="utf-8")).get("apply") or {}
    return ApplySettings(**{**raw, "auto_submit_enabled": False, "cover_letter_mode": "off"})


def measures(result: store_models.FillResult | None, progress: list[str]) -> dict:
    if result is None:
        return {}
    steps = [int(m.group(1)) for line in progress if (m := _STEP.search(line))]
    reasons = Counter(
        str(item.get("reason") or "")[:60] for item in result.leftovers if isinstance(item, dict)
    )
    return {
        "status": result.status,
        "handoff": (result.handoff_reason or "")[:160],
        "steps_reached": max(steps, default=0),
        "filled": len(result.filled),
        "committed": len(result.field_outcomes),
        "required_left": len(result.required_empty),
        "leftover_reasons": dict(reasons),
        "final_step_reached": result.final_step_reached,
        "uploads": [u.get("state") for u in result.uploads if isinstance(u, dict)],
    }


def _progress_log(progress: list[str], started: float):
    """Keep each progress line, and write it to ``<tag>.progress.log`` at once, so a run
    cut by the parent's time limit still shows where it stopped."""
    log = (OUT / f"{TAG}.progress.log").open("w", encoding="utf-8")

    def record(message: str) -> None:
        line = f"{time.monotonic() - started:6.1f}s {message}"
        progress.append(line)
        log.write(line + "\n")
        log.flush()

    return record


def main() -> int:
    _patch()
    progress: list[str] = []
    started = time.monotonic()
    result, error = None, ""
    try:
        app = _app()
        run = fill_mod._FillRun(
            app,
            source_job_id=app.source_job_id,
            settings=_settings(),
            submit_mode="awaiting_review",
            fill_mode="initial",
            should_cancel=None,
            on_progress=_progress_log(progress, started),
            applicant_profile=synth.PROFILE,
        )
        result = run.run()
        with contextlib.suppress(Exception), _original_cdp() as connected:
            for page in connected.contexts[0].pages:
                if page.url.startswith("http"):
                    page.screenshot(path=str(OUT / f"{TAG}.png"), full_page=True)
                    if os.environ.get("PROBE_CAPTURE"):  # the page as the fill left it
                        for index, frame in enumerate(page.frames):
                            with contextlib.suppress(Exception):
                                name = "end" if index == 0 else f"end.frame{index}"
                                capture_form.capture(frame, OUT / "captures" / f"{TAG}.{name}.html")
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()[-2000:]
    AUDIT.close()
    report = {
        "tag": TAG,
        "url": URL,
        "seconds": round(time.monotonic() - started, 1),
        "calls": dict(CALLS),
        "resolver_asked": ASKED,
        "error": error,
        "measures": measures(result, progress),
        "audit": AUDIT.summary(),
        "progress": progress,
        "labels": [
            {"label": str(i.get("label") or "")[:120], "reason": str(i.get("reason") or "")[:60]}
            for i in (result.leftovers if result else [])
            if isinstance(i, dict)
        ],
    }
    (OUT / f"{TAG}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    m = report["measures"]
    print(
        json.dumps(
            {
                "s": report["seconds"],
                "status": m.get("status"),
                "filled": m.get("filled"),
                "committed": m.get("committed"),
                "leaks": report["audit"]["allowed_with_applicant_data"],
                "error": error.splitlines()[-1][:150] if error else "",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
