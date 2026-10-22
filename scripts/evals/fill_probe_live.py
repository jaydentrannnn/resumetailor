"""`fill_probe.py live`, one target: the real fill with the made-up applicant, guarded.

Run by `fill_probe.py` in a child process whose environment already points every app path
at a throwaway sandbox and ``CHROME_CDP_URL`` at the probe's own Chrome.

A test-account target (``PROBE_ACCOUNT_SITE`` set by the parent) signs up as that site's
inbox alias (`fill_probe_inbox`) with a password kept in ``PROBE_ACCOUNTS_DIR``, may write
to its own ATS hosts (``PROBE_ATS_HOSTS``, see `fill_probe_guard`), and when the fill
stops for an email code or link, reads it from the inbox, enters it under the guard and
continues the fill (at most `_VERIFY_ROUNDS` times). `clicks.submit_click` raises in every
mode. `fill_probe_observe.Observer` screenshots and reads back the page before each
advance and at the end.

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
from types import SimpleNamespace
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_form  # noqa: E402
import fill_probe_data as synth  # noqa: E402
import fill_probe_guard  # noqa: E402
import fill_probe_inbox  # noqa: E402
import fill_probe_observe  # noqa: E402

from resume_tailor import config  # noqa: E402
from resume_tailor.apply.answers import answer, hybrid_resolver, resolver_basis  # noqa: E402
from resume_tailor.apply.answers import profile as profile_mod  # noqa: E402
from resume_tailor.apply.ats import workday_auth  # noqa: E402
from resume_tailor.apply.discovery import fetch_jd  # noqa: E402
from resume_tailor.apply.driver import browser, clicks  # noqa: E402
from resume_tailor.apply.forms import fill as fill_mod  # noqa: E402
from resume_tailor.apply.funnel import store, store_models  # noqa: E402
from resume_tailor.infra import secret_store  # noqa: E402
from resume_tailor.web.schemas import ApplySettings  # noqa: E402

OUT, TAG, URL = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
ATS = sys.argv[4] if len(sys.argv) > 4 else ""
AUDIT = fill_probe_guard.Audit(OUT / f"{TAG}.requests.jsonl")
CALLS: Counter[str] = Counter()
CLIENTS = [0]  # classifier client builds: one per model call
ASKED: list[dict[str, str]] = []  # controls the resolver put to the model (labels only)
BASIS: list[dict] = []  # each basis check of a model answer (`_basis_recorded`)
_STEP = re.compile(r"scanning form step (\d+)")
OBSERVER = fill_probe_observe.Observer(OUT, TAG)
SITE = os.environ.get("PROBE_ACCOUNT_SITE", "")
ATS_HOSTS = tuple(h for h in os.environ.get("PROBE_ATS_HOSTS", "").split(",") if h)
ACCOUNTS = Path(os.environ.get("PROBE_ACCOUNTS_DIR") or OUT / "accounts")
_VERIFY_ROUNDS = 2
_CODE_INPUTS = (
    "input[data-automation-id='verificationCode'], input[autocomplete='one-time-code'], "
    "input[name*='code' i]:not([type=hidden]), input[id*='code' i]:not([type=hidden])"
)


def _account() -> tuple[str, str]:
    """(alias, password) of this site's test account; the password is made once and kept."""
    user, _ = fill_probe_inbox.credentials()
    if not user:
        raise RuntimeError(f"account target without a test inbox ({fill_probe_inbox.ENV_FILE})")
    ACCOUNTS.mkdir(parents=True, exist_ok=True)
    path = ACCOUNTS / "passwords.json"
    known = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if SITE not in known:
        known[SITE] = workday_auth.generate_compliant_password()
        path.write_text(json.dumps(known, indent=1), encoding="utf-8")
    return fill_probe_inbox.alias(user, SITE), known[SITE]


ALIAS, PASSWORD = _account() if SITE else ("", "")
PROFILE = (
    synth.PROFILE.model_copy(
        update={"email": ALIAS, "workday_email": ALIAS, "workday_password": PASSWORD}
    )
    if SITE
    else synth.PROFILE
)
#: The alias's digest part is the marker: its "+" reads as a space once URL-decoded.
MARKERS = synth.MARKERS + ((ALIAS.split("+", 1)[1].split("@")[0].encode(),) if SITE else ())


def _vault(direction: str) -> None:
    """Copy this site's Workday vault (account flags) in from, or out to, ``ACCOUNTS``."""
    kept = ACCOUNTS / "vaults" / f"{re.sub(r'[^A-Za-z0-9.-]+', '_', SITE)}.json"
    live = config.APPLICATIONS_OUTPUT_DIR / "workday_vault.json"
    source, target = (kept, live) if direction == "in" else (live, kept)
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


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


def _upload() -> tuple[str, bytes] | None:
    """SmartRecruiters' own host and the made-up resume it may receive (the user allowed
    this upload, 2026-10-21); None for every other platform."""
    if (ATS or fetch_jd.detect_ats(URL)).lower() != "smartrecruiters":
        return None
    resume = config.OUTPUT_DIR / "jobs" / f"probe-{TAG}" / "tailored.pdf"
    host = (urlsplit(URL).hostname or "").lower()
    return (host, resume.read_bytes()) if host and resume.is_file() else None


_original_cdp = browser.cdp_browser


@contextlib.contextmanager
def _guarded_cdp():
    with _original_cdp() as connected:
        context = connected.contexts[0] if connected.contexts else connected.new_context()
        fill_probe_guard.install(context, AUDIT, MARKERS, synth.ANSWER_MARKERS, ATS_HOSTS,
                                 _upload())
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


def _basis_recorded(fn):
    """Keep each basis check of a model answer: the question, the option picked, the
    basis it cited, the verdict, and which of the checks held. The applicant is made up,
    so the cited fact may be recorded."""
    def wrapper(action, field, *, profile, packet_fields, skills):
        verdict = fn(action, field, profile=profile, packet_fields=packet_fields, skills=skills)
        entry = {
            "label": str(field.get("label") or "")[:160], "type": str(field.get("type") or ""),
            "options": [str(o)[:60] for o in (field.get("options") or [])][:40],
            "action": action.action, "value": str(action.value)[:120],
            "basis_kind": action.basis_kind, "basis_key": action.basis_key, "supported": verdict,
        }
        with contextlib.suppress(Exception):
            question = resolver_basis._question(field)
            entry["as_worded"] = resolver_basis._as_worded(question)
            if action.basis_kind in {"profile", "packet"}:
                key, fact, _custom = resolver_basis._fact(
                    action, question, profile=profile, packet_fields=packet_fields
                )
                entry.update(fact_key=key, fact=str(fact)[:120],
                             about=resolver_basis._about(key, question),
                             says=resolver_basis._says(action, question, key, fact))
        BASIS.append(entry)
        return verdict

    return wrapper


def _no_submit(*_args, **_kwargs):
    CALLS["submit_click_refused"] += 1
    raise clicks.SubmitRefused("the fill probe never submits")


def _observed_click(fn):
    """Snapshot the page before each advance click (what this step showed when the fill
    moved on)."""
    def wrapper(loc, *args, purpose, **kwargs):
        if purpose == "advance":
            with contextlib.suppress(Exception):
                OBSERVER.snapshot(loc.page, "advance")
        return fn(loc, *args, purpose=purpose, **kwargs)

    return wrapper


_KEPT_SECRETS: dict[str, str] = {}
#: The Workday vault's and the profile's password store in this process: test-account
#: passwords never reach the OS keychain, where a sandbox's "profile:default:workday:<site>"
#: would be the owner's real entry. (Model connections still read the keychain.)
PROBE_SECRETS = SimpleNamespace(
    SecretStoreError=secret_store.SecretStoreError,
    profile_name=secret_store.profile_name,
    get=_KEPT_SECRETS.get,
    set=_KEPT_SECRETS.__setitem__,
    delete=lambda name: _KEPT_SECRETS.pop(name, None),
)


def _patch() -> None:
    workday_auth.secret_store = PROBE_SECRETS
    profile_mod.secret_store = PROBE_SECRETS
    browser.cdp_browser = _guarded_cdp
    fill_mod.browser.cdp_browser = _guarded_cdp
    clicks.submit_click = _no_submit
    clicks.safe_click = _observed_click(clicks.safe_click)
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
    resolver_basis.supported = _basis_recorded(resolver_basis.supported)


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


def _fill_page(connected, result: store_models.FillResult | None):
    """The fill's own tab, else the last web page open."""
    context = connected.contexts[0]
    page = browser.find_target(context, result.browser_target_id) if result else None
    pages = [p for p in context.pages if not p.is_closed() and p.url.startswith("http")]
    return page or (pages[-1] if pages else None)


def _enter_code(page, code: str) -> bool:
    """Type ``code`` into the page's code box (or its one-character boxes) and press Enter."""
    for frame in page.frames:
        boxes = [b for b in frame.locator(_CODE_INPUTS).all() if b.is_visible()]
        if not boxes:
            continue
        if len(boxes) >= len(code) >= 4:
            for box, char in zip(boxes, code, strict=False):
                box.fill(char)
        else:
            boxes[0].fill(code)
        boxes[-1].press("Enter")
        page.wait_for_timeout(5_000)
        return True
    return False


def _verify(result: store_models.FillResult, since: float, log) -> str:
    """Read the email code or link sent to the alias and use it on the fill's tab, under
    the guard; how it went, for the report."""
    log(f"probe: waiting for the verification email to the test alias ({SITE})")
    found = fill_probe_inbox.wait_for(ALIAS, since)
    if not (found.code or found.link):
        return "no_email"
    with _guarded_cdp() as connected:
        page = _fill_page(connected, result)
        if page is None:
            return "no_page"
        if found.code and _enter_code(page, found.code):
            log("probe: entered the emailed code")
            return "code"
        if found.link:
            page.goto(found.link, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(5_000)
            log("probe: opened the emailed verification link")
            return "link"
    return "code_without_box"


def _fill(app, mode: str, log) -> store_models.FillResult:
    return fill_mod._FillRun(
        app,
        source_job_id=app.source_job_id,
        settings=_settings(),
        submit_mode="awaiting_review",
        fill_mode=mode,
        should_cancel=None,
        on_progress=log,
        applicant_profile=PROFILE,
    ).run()


def _end_of_fill(result: store_models.FillResult | None) -> None:
    """The last snapshot, the end screenshot and (``PROBE_CAPTURE``) the page as the fill
    left it; with ``PROBE_HOLD``, keep the guarded connection open until
    ``<tag>.release`` appears (30 minutes at most) for a read-only look."""
    with contextlib.suppress(Exception), _guarded_cdp() as connected:
        page = _fill_page(connected, result)
        if page is None:
            return
        OBSERVER.snapshot(page, "end")
        page.screenshot(path=str(OUT / f"{TAG}.png"), full_page=True)
        if os.environ.get("PROBE_CAPTURE"):
            for index, frame in enumerate(page.frames):
                with contextlib.suppress(Exception):
                    name = "end" if index == 0 else f"end.frame{index}"
                    capture_form.capture(frame, OUT / "captures" / f"{TAG}.{name}.html")
        if os.environ.get("PROBE_HOLD"):
            release = OUT / f"{TAG}.release"
            stop = time.monotonic() + 1800
            print(json.dumps({"held": TAG, "release": str(release)}), flush=True)
            while not release.exists() and time.monotonic() < stop:
                page.wait_for_timeout(2_000)


def main() -> int:
    _patch()
    progress: list[str] = []
    started = time.monotonic()
    result, error = None, ""
    verification: list[str] = []
    try:
        app = _app()
        log = _progress_log(progress, started)
        if SITE:
            _vault("in")
        since = time.time()
        result = _fill(app, "initial", log)
        while SITE and result.status == "awaiting_otp" and len(verification) < _VERIFY_ROUNDS:
            verification.append(_verify(result, since, log))
            if verification[-1] in {"no_email", "no_page", "code_without_box"}:
                break
            since = time.time()
            result = _fill(store.get(app.source_job_id), "continue", log)
        _end_of_fill(result)
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()[-2000:]
    finally:
        if SITE:
            with contextlib.suppress(Exception):
                _vault("out")
    AUDIT.close()
    measured = measures(result, progress)
    report = {
        "tag": TAG,
        "url": URL,
        "ats": ATS or fetch_jd.detect_ats(URL),
        "account": bool(SITE),
        "verification": verification,
        "seconds": round(time.monotonic() - started, 1),
        "calls": dict(CALLS),
        "resolver_asked": ASKED,
        "basis": BASIS,
        "error": error,
        "measures": measured,
        "fill_end": fill_probe_observe.fill_end(measured, error=error),
        "grades": fill_probe_observe.grade(
            [o for o in (result.field_outcomes if result else []) if isinstance(o, dict)],
            OBSERVER.snapshots,
            PROFILE,
            leftovers=[i for i in (result.leftovers if result else []) if isinstance(i, dict)],
            required_empty=list(result.required_empty) if result else [],
        ),
        "observed": OBSERVER.report(),
        # The made-up applicant's fill record, kept whole so the grade can be re-run offline.
        "raw": {
            "field_outcomes": list(result.field_outcomes) if result else [],
            "leftovers": list(result.leftovers) if result else [],
            "required_empty": list(result.required_empty) if result else [],
        },
        "diagnostics": (result.diagnostics if result else None) or {},
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
                "end": report["fill_end"],
                "grades": report["grades"]["counts"],
                "verification": verification,
                "leaks": report["audit"]["allowed_with_applicant_data"],
                "submit_refused": report["audit"]["submit_refused"],
                "error": error.splitlines()[-1][:150] if error else "",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
