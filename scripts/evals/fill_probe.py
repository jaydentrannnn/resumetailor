"""Measure autofill on live postings, read-only or with a made-up applicant.

Two modes, both in a throwaway data dir and a separate off-screen Chrome (never the
app's browser, profile or data):

``read-only``  open each posting and enter its form the way Fill does (navigation only),
               then run the screen classifier, `filler.js` in scan mode, the rules and the
               model fallback (the app's Fill model), the recovery scanner and a widget
               census. Nothing is typed. ``--capture`` also saves each landed page
               (open shadow roots included) under ``<out>/captures/`` for building
               fixtures; captures stay local (``output/`` is gitignored).
``live``       run the real fill (`forms.fill._FillRun`) on each ``live`` target with the
               made-up applicant (`fill_probe_data`), ``submit_mode="awaiting_review"``,
               one child process per target. `fill_probe_guard` aborts every request that
               carries the applicant's data, an upload or an unreadable body, and blocks
               WebSockets and service workers; every request is audited to
               ``<tag>.requests.jsonl``.
``summary``    print per-target measures of one or two result dirs (before/after).

Targets are a TSV outside the repo (``tag<TAB>url<TAB>ats<TAB>modes``; modes is
``live`` or ``read-only``, default live), by default
``%LOCALAPPDATA%/ResumeTailorData/evals/fill_targets.tsv``.

    python scripts/evals/fill_probe.py read-only --out output/evals/ro-1
    python scripts/evals/fill_probe.py live --out output/evals/live-1 --only lever2,ashby1
    python scripts/evals/fill_probe.py summary output/evals/live-1 output/evals/live-2
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DEFAULT_TARGETS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "ResumeTailorData" / "evals" / "fill_targets.tsv"
)
CHROMES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
_SKIP_LIVE = frozenset({"workday", "icims", "oracle"})
#: A read-only probe of one posting that runs longer than this is cut.
READ_ONLY_LIMIT_S = 240


def sandbox_env(base: Path, port: int) -> dict[str, str]:
    """Environment that points every app path at ``base`` and the browser at ``port``."""
    for name in ("data", "output", "templates", "cache", "logs"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return {
        "RESUME_TAILOR_DATA_DIR": str(base / "data"),
        "RESUME_TAILOR_OUTPUT_DIR": str(base / "output"),
        "RESUME_TAILOR_TEMPLATES_DIR": str(base / "templates"),
        "RESUME_TAILOR_CACHE_DIR": str(base / "cache"),
        "RESUME_TAILOR_LOG_DIR": str(base / "logs"),
        "RESUME_TAILOR_BROWSER_LAUNCH": "off",
        "CHROME_CDP_URL": f"http://127.0.0.1:{port}",
        "APPLY_FILL_ENGINE": "legacy",
    }


def read_targets(path: Path, only: set[str]) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        tag, url, ats, modes = (line.split("\t") + ["", "", ""])[:4]
        if only and tag not in only:
            continue
        rows.append(
            {
                "tag": tag.strip(),
                "url": url.strip(),
                "ats": ats.strip(),
                "modes": modes.strip() or "live",
            }
        )
    return rows


def launch_chrome(profile: Path, port: int) -> subprocess.Popen:
    exe = next((c for c in CHROMES if Path(c).is_file()), None)
    if exe is None:
        raise SystemExit("no Chrome or Edge found")
    # Headed but off-screen: SmartRecruiters' bot wall stops headless Chrome.
    proc = subprocess.Popen(
        [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--window-position=-32000,-32000",
            "--window-size=1400,1000",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        with contextlib.suppress(Exception):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            return proc
        time.sleep(0.5)
    stop_chrome(proc)
    raise SystemExit("browser did not start")


def stop_chrome(proc: subprocess.Popen) -> None:
    """Stop the Chrome this script launched (its own PID only)."""
    proc.terminate()
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)
    if proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
        )


# -- live ----------------------------------------------------------------------------------


def run_live(targets: list[dict[str, str]], out: Path, port: int) -> None:
    for target in targets:
        if target["modes"] != "live" or (target["ats"] or "").lower() in _SKIP_LIVE:
            print("skip (read-only target)", target["tag"], flush=True)
            continue
        sandbox = out / "sandboxes" / target["tag"]
        env = {**os.environ, **sandbox_env(sandbox, port), "PYTHONPATH": str(ROOT / "src")}
        proc = launch_chrome(sandbox / "chrome", port)
        try:
            done = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "fill_probe_live.py"),
                    str(out),
                    target["tag"],
                    target["url"],
                    target["ats"],
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=900,
            )
            tail = (done.stdout or "").strip().splitlines()[-1:] or (
                done.stderr or ""
            ).strip().splitlines()[-3:]
            print(target["tag"], *tail, flush=True)
        except subprocess.TimeoutExpired:
            print(target["tag"], "timed out", flush=True)
        finally:
            stop_chrome(proc)


def _close_pages(port: int) -> None:
    """Close every tab but one through the DevTools HTTP endpoint (works on a hung page)."""
    with contextlib.suppress(Exception):
        pages = [
            t
            for t in json.loads(
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5).read()
            )
            if t.get("type") == "page"
        ]
        for target in pages[1:]:
            with contextlib.suppress(Exception):
                urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/close/{target['id']}", timeout=5
                )


def run_read_only(targets: list[dict[str, str]], out: Path, port: int, *, capture: bool) -> None:
    """One child per target with a time limit, all in one Chrome and one sandbox."""
    env = {**os.environ, **sandbox_env(out / "sandbox", port), "PYTHONPATH": str(ROOT / "src")}
    proc = launch_chrome(out / "sandbox" / "chrome", port)
    try:
        for target in targets:
            args = [
                sys.executable,
                str(HERE / "fill_probe_read.py"),
                str(out),
                str(port),
                target["tag"],
                target["url"],
                target["ats"],
                *(["--capture"] if capture else []),
            ]
            try:
                done = subprocess.run(
                    args,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                    timeout=READ_ONLY_LIMIT_S,
                )
                lines = (done.stdout or "").strip().splitlines() or (
                    done.stderr or ""
                ).strip().splitlines()[-3:]
                print(*lines[-1:], flush=True)
            except subprocess.TimeoutExpired:
                (out / f"{target['tag']}.json").write_text(
                    json.dumps(
                        {
                            "tag": target["tag"],
                            "url": target["url"],
                            "error": f"timed out after {READ_ONLY_LIMIT_S}s",
                        }
                    ),
                    encoding="utf-8",
                )
                print(target["tag"], "timed out", flush=True)
            _close_pages(port)
    finally:
        stop_chrome(proc)


# -- summary -------------------------------------------------------------------------------


def _row(report: dict) -> dict:
    if "questions" in report:  # read-only
        qs = report.get("questions") or []
        req = [q for q in qs if q.get("required")]
        return {
            "screen": report.get("state_after"),
            "questions": len(qs),
            "rule": sum(1 for q in qs if q.get("rule_key")),
            "keyed": sum(1 for q in qs if q.get("rule_key") or q.get("model_key")),
            "req": len(req),
            "req_keyed": sum(1 for q in req if q.get("rule_key") or q.get("model_key")),
            "model_calls": report.get("model_asked_batches", 0),
            "s": report.get("seconds"),
        }
    m = report.get("measures") or {}
    return {
        "screen": m.get("status"),
        "steps": m.get("steps_reached"),
        "filled": m.get("filled"),
        "committed": m.get("committed"),
        "req_left": m.get("required_left"),
        "model_calls": sum((report.get("calls") or {}).values()),
        "s": report.get("seconds"),
        "leaks": (report.get("audit") or {}).get("allowed_with_applicant_data"),
    }


def summary(dirs: list[Path]) -> None:
    runs = [
        {
            p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in d.glob("*.json")
            if p.stem != "audit"
        }
        for d in dirs
    ]
    tags = sorted(set().union(*runs))
    totals = [Counter() for _ in runs]
    for tag in tags:
        cells = []
        for index, run in enumerate(runs):
            report = run.get(tag)
            if report is None:
                cells.append("-")
                continue
            row = _row(report)
            totals[index].update(
                {k: v for k, v in row.items() if isinstance(v, (int, float)) and k != "s"}
            )
            cells.append(" ".join(f"{k}={v}" for k, v in row.items()))
        print(f"{tag:12} " + "  ||  ".join(cells))
    for index, total in enumerate(totals):
        print(f"TOTAL[{index}] " + " ".join(f"{k}={v}" for k, v in sorted(total.items())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["read-only", "live", "summary"])
    parser.add_argument("dirs", nargs="*", type=Path, help="summary: result dirs")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", default="")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    if args.mode == "summary":
        summary(args.dirs)
        return 0
    out = (
        args.out or ROOT / "output" / "evals" / f"{args.mode}-{time.strftime('%Y%m%d-%H%M%S')}"
    ).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = read_targets(args.targets, {t for t in args.only.split(",") if t})
    if args.mode == "live":
        run_live(targets, out, args.port)
        return 0
    run_read_only(targets, out, args.port, capture=args.capture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
