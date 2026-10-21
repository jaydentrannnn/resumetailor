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
               Each live report also holds per-step screenshots and readbacks, every field
               outcome graded against the page (`fill_probe_observe`) and why the fill
               ended. ``--workers N`` runs N browsers at once (ports upward from
               ``--port``); ``--hold`` keeps a finished page open and guarded for a
               read-only look until ``<out>/<tag>.release`` exists.
``summary``    print per-target measures of one or two result dirs (before/after);
               ``--by-ats`` adds how fills ended, field grades and failure buckets per
               platform.

Targets are a TSV outside the repo (``tag<TAB>url<TAB>ats<TAB>modes<TAB>account``; modes
is ``live`` or ``read-only``, default live), by default
``%LOCALAPPDATA%/ResumeTailorData/evals/fill_targets.tsv`` (`fill_probe_targets` builds
one from the owner's applications). Workday, iCIMS, Oracle, Taleo and SuccessFactors run
live only as ``account`` targets: a test account on the inbox `fill_probe_inbox` reads,
which may write its own ATS host and never submits.

    python scripts/evals/fill_probe.py read-only --out output/evals/ro-1
    python scripts/evals/fill_probe.py live --out output/evals/live-1 --only lever2,ashby1
    python scripts/evals/fill_probe.py live --targets batch3.tsv --workers 3 --capture
    python scripts/evals/fill_probe.py summary output/evals/live-1 output/evals/live-2 --by-ats
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fill_probe_targets  # noqa: E402

DEFAULT_TARGETS = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "ResumeTailorData" / "evals" / "fill_targets.tsv"
)
CHROMES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
#: Live targets of these platforms need a test account (an ``account`` target column).
_ACCOUNT_ONLY = frozenset({"workday", "icims", "oracle", "taleo", "successfactors"})
ACCOUNTS_DIR = DEFAULT_TARGETS.parent / "test_accounts"
#: A live fill of one posting that runs longer than this is cut.
LIVE_LIMIT_S = 900
#: Seconds between two test-account sign-ups (random in this range).
SIGNUP_GAP_S = (20, 60)
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
        # Model connections are read from the OS keychain as the app reads them; the live
        # child keeps test-account passwords out of it (`fill_probe_live.PROBE_SECRETS`).
    }


def read_targets(path: Path, only: set[str]) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        tag, url, ats, modes, account = (line.split("\t") + ["", "", "", ""])[:5]
        if only and tag not in only:
            continue
        rows.append(
            {
                "tag": tag.strip(),
                "url": url.strip(),
                "ats": ats.strip(),
                "modes": modes.strip() or "live",
                "account": account.strip(),
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


def ats_hosts(url: str, ats: str) -> list[str]:
    """The hosts a test-account target may write to: the posting's own host, and for
    iCIMS its login domain."""
    host = (urlsplit(url).hostname or "").lower()
    return [h for h in (host, "icims.com" if ats == "icims" else "") if h]


def live_skip(target: dict[str, str]) -> str:
    """Why a live run leaves this target out ("" to run it)."""
    if target["modes"] != "live":
        return "read-only target"
    if (target["ats"] or "").lower() in _ACCOUNT_ONLY and target.get("account") != "account":
        return "needs a test account"
    return ""


def _live_one(target: dict[str, str], out: Path, port: int, extra: dict[str, str]) -> None:
    sandbox = out / "sandboxes" / target["tag"]
    env = {**os.environ, **sandbox_env(sandbox, port), "PYTHONPATH": str(ROOT / "src"), **extra}
    if target.get("account") == "account":
        ats, owner = fill_probe_targets.site_key(target["url"])
        env |= {
            "PROBE_ACCOUNT_SITE": f"{ats}:{owner}",
            "PROBE_ATS_HOSTS": ",".join(ats_hosts(target["url"], target["ats"])),
            "PROBE_ACCOUNTS_DIR": str(ACCOUNTS_DIR),
        }
    limit = LIVE_LIMIT_S + (1800 if extra.get("PROBE_HOLD") else 0)
    proc = launch_chrome(sandbox / "chrome", port)
    try:
        done = subprocess.run(
            [sys.executable, str(HERE / "fill_probe_live.py"), str(out), target["tag"],
             target["url"], target["ats"]],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=limit,
        )
        tail = (done.stdout or "").strip().splitlines()[-1:] or (
            done.stderr or ""
        ).strip().splitlines()[-3:]
        print(target["tag"], *tail, flush=True)
    except subprocess.TimeoutExpired:
        report = out / f"{target['tag']}.json"
        if not report.is_file():
            report.write_text(
                json.dumps({"tag": target["tag"], "url": target["url"], "ats": target["ats"],
                            "timed_out": True, "fill_end": "timeout", "measures": {}}),
                encoding="utf-8",
            )
        print(target["tag"], "timed out", flush=True)
    finally:
        stop_chrome(proc)


def run_live(
    targets: list[dict[str, str]], out: Path, port: int, *, workers: int = 1,
    extra: dict[str, str] | None = None,
) -> None:
    """Each target in its own sandbox and Chrome, ``workers`` at a time on ports ``port``
    upward. Two targets on one site (a Workday tenant, a board) never run at once, and
    test-account sign-ups start `SIGNUP_GAP_S` apart."""
    queue = []
    for target in targets:
        reason = live_skip(target)
        if reason:
            print(f"skip ({reason})", target["tag"], flush=True)
        else:
            queue.append(target)
    lock = threading.Lock()
    busy: set[tuple[str, str]] = set()
    last_signup, next_gap = [0.0], [0.0]

    def take() -> dict[str, str] | None:
        while True:
            with lock:
                if not queue:
                    return None
                for index, target in enumerate(queue):
                    site = fill_probe_targets.site_key(target["url"])
                    if site in busy:
                        continue
                    if target.get("account") == "account":
                        if time.monotonic() - last_signup[0] < next_gap[0]:
                            continue
                        last_signup[0] = time.monotonic()
                        next_gap[0] = random.uniform(*SIGNUP_GAP_S)
                    busy.add(site)
                    return queue.pop(index)
            time.sleep(2)

    def worker(slot: int) -> None:
        while (target := take()) is not None:
            try:
                _live_one(target, out, port + slot, extra or {})
            finally:
                with lock:
                    busy.discard(fill_probe_targets.site_key(target["url"]))

    threads = [threading.Thread(target=worker, args=(slot,)) for slot in range(max(1, workers))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


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
        **({"end": report["fill_end"]} if report.get("fill_end") else {}),
        **({"ok": (report.get("grades") or {}).get("counts", {}).get("ok", 0)}
           if report.get("grades") else {}),
    }


#: Field grades that are not failures.
_FINE = frozenset({"ok", "unanswered_optional"})


def breakdown(reports: list[dict]) -> dict[str, Counter]:
    """Live reports counted by platform: how fills ended, how fields graded, and failure
    buckets (an end that is not ``reached_review``, or a failing field grade, by widget
    kind), each bucket keyed ``(ats, what, kind)``."""
    ends, grades, buckets, postings = Counter(), Counter(), Counter(), Counter()
    for report in reports:
        if "questions" in report:  # read-only
            continue
        ats = report.get("ats") or "unknown"
        end = report.get("fill_end") or ("timeout" if report.get("timed_out") else "no_result")
        postings[ats] += 1
        ends[(ats, end)] += 1
        if end != "reached_review":
            buckets[(ats, f"end:{end}", "")] += 1
        graded = report.get("grades") or {}
        for field in graded.get("fields") or []:
            grades[(ats, field["grade"])] += 1
            if field["grade"] not in _FINE:
                buckets[(ats, field["grade"], field.get("kind") or "?")] += 1
        for field in graded.get("unrecorded_blank_required") or []:
            grades[(ats, "blank_required_unrecorded")] += 1
            buckets[(ats, "blank_required_unrecorded", field.get("kind") or "?")] += 1
    return {"postings": postings, "ends": ends, "grades": grades, "buckets": buckets}


def _per_ats(counts: Counter, ats: str) -> str:
    cells = sorted(((what, n) for (a, what), n in counts.items() if a == ats), key=lambda c: -c[1])
    return " ".join(f"{what}={n}" for what, n in cells)


def print_breakdown(reports: list[dict]) -> None:
    table = breakdown(reports)
    print("\nPOSTINGS " + " ".join(f"{a}={n}" for a, n in table["postings"].most_common()))
    print("\nHOW FILLS ENDED (ats: end=count)")
    for ats in table["postings"]:
        print(f"  {ats:16} " + _per_ats(table["ends"], ats))
    print("\nFIELD GRADES (ats: grade=count)")
    for ats in table["postings"]:
        print(f"  {ats:16} " + _per_ats(table["grades"], ats))
    print("\nTOP FAILURE BUCKETS (count  ats  what  kind)")
    for (ats, what, kind), n in table["buckets"].most_common(40):
        print(f"  {n:4}  {ats:16} {what:28} {kind}")


def summary(dirs: list[Path], *, by_ats: bool = False) -> None:
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
    if by_ats:
        for index, run in enumerate(runs):
            print(f"\n=== {dirs[index]}")
            print_breakdown(list(run.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=["read-only", "live", "summary"])
    parser.add_argument("dirs", nargs="*", type=Path, help="summary: result dirs")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", default="")
    parser.add_argument("--port", type=int, default=9333)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--workers", type=int, default=1, help="live: browsers at once")
    parser.add_argument("--hold", action="store_true",
                        help="live: keep each page guarded and open until <tag>.release appears")
    parser.add_argument("--by-ats", action="store_true", help="summary: platform breakdown")
    args = parser.parse_args()
    if args.mode == "summary":
        summary(args.dirs, by_ats=args.by_ats)
        return 0
    out = (
        args.out or ROOT / "output" / "evals" / f"{args.mode}-{time.strftime('%Y%m%d-%H%M%S')}"
    ).resolve()
    out.mkdir(parents=True, exist_ok=True)
    targets = read_targets(args.targets, {t for t in args.only.split(",") if t})
    if args.mode == "live":
        extra = {
            **({"PROBE_CAPTURE": "1"} if args.capture else {}),
            **({"PROBE_HOLD": "1"} if args.hold else {}),
        }
        run_live(targets, out, args.port, workers=args.workers, extra=extra)
        return 0
    run_read_only(targets, out, args.port, capture=args.capture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
