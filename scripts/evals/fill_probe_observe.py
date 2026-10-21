"""What the page showed while `fill_probe.py live` filled it, and how each answer held up.

`Observer` runs in the live child. Before each advance click and once at the end it saves a
full-page screenshot (``<tag>.stepNN.png``) and a readback of every visible control on
every frame (`fill_probe_readback.js`: label, kind, required, shown value, invalid flag,
the form's message). The applicant is made up, so shown values may be recorded. Page
console errors are counted, with the first few lines kept.

`grade` and `fill_end` are pure and run anywhere: `grade` sets each field outcome the fill
recorded beside the last readback row with the same label, and checks it against the
page and the made-up applicant's profile; `fill_end` names why the fill stopped.
"""

from __future__ import annotations

import contextlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from resume_tailor.apply.forms import fill_page
from resume_tailor.apply.funnel.answer_harvest import _same_answer

HERE = Path(__file__).resolve().parent
READBACK_JS = fill_page.with_dom_common(
    (HERE / "fill_probe_readback.js").read_text(encoding="utf-8")
)
#: Field outcome states where the fill says the page holds its answer.
_HELD = frozenset({"verified_filled", "preserved"})
_CONSOLE_KEEP = 5


class Observer:
    """Screenshots and readbacks of the live page, for one probe target."""

    def __init__(self, out: Path, tag: str) -> None:
        self.out, self.tag = out, tag
        self.snapshots: list[dict[str, Any]] = []
        self.errors: Counter[str] = Counter()
        self.console: list[str] = []
        self.console_errors = 0
        self._pages: set[int] = set()

    def watch(self, page: Any) -> None:
        """Count the page's console errors (once per page)."""
        if id(page) in self._pages:
            return
        self._pages.add(id(page))

        def on_console(msg: Any) -> None:
            with contextlib.suppress(Exception):
                if msg.type == "error":
                    self.console_errors += 1
                    if len(self.console) < _CONSOLE_KEEP:
                        self.console.append(str(msg.text)[:200])

        with contextlib.suppress(Exception):
            page.on("console", on_console)

    def snapshot(self, page: Any, why: str) -> None:
        """Screenshot and read back ``page`` now; a failure is counted, never raised."""
        self.watch(page)
        number = len(self.snapshots) + 1
        shot = self.out / f"{self.tag}.step{number:02d}.png"
        entry: dict[str, Any] = {"n": number, "why": why, "url": "", "frames": [], "png": ""}
        try:
            entry["url"] = str(page.url)
            page.screenshot(path=str(shot), full_page=True, timeout=15_000)
            entry["png"] = shot.name
        except Exception as exc:  # noqa: BLE001
            self.errors[f"screenshot: {type(exc).__name__}"] += 1
        for index, frame in enumerate(page.frames):
            try:
                read = frame.evaluate(READBACK_JS)
            except Exception as exc:  # noqa: BLE001 - a detached or cross-origin frame
                self.errors[f"readback: {type(exc).__name__}"] += 1
                continue
            if read and (read.get("rows") or read.get("alerts")):
                entry["frames"].append({"frame": index, **read})
        self.snapshots.append(entry)

    def report(self) -> dict[str, Any]:
        return {
            "snapshots": self.snapshots,
            "observe_errors": dict(self.errors),
            "console_errors": self.console_errors,
            "console_first": self.console,
        }


#: Labels compare on their first characters: the fill's record and the readback cut
#: long questions at different lengths.
_LABEL_CHARS = 60


def flat_label(label: str) -> str:
    """A label as compared across the fill's record and the readback."""
    text = re.sub(r"\(required\)|\brequired\b|\*", " ", str(label or "").casefold())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()[:_LABEL_CHARS].strip()


def _rows(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The last readback row seen for each label (a later step's row wins)."""
    latest: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        for frame in snap.get("frames") or []:
            for row in frame.get("rows") or []:
                key = flat_label(row.get("label", ""))
                if key:
                    latest[key] = {**row, "step": snap.get("n")}
    return latest


def _truth(key: str, profile: Any) -> str:
    """The profile's own text for ``key`` (yes/no and numeric facts are worded by the
    form, so they are not compared)."""
    value = getattr(profile, key, None) if key else None
    return value if isinstance(value, str) else ""


def _contradicts(truth: str, given: str) -> bool:
    """The answer is neither the profile's text written another way nor contains it
    ("Sacramento, California, United States" holds the city "Sacramento")."""
    flat = lambda s: re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()  # noqa: E731
    return not (_same_answer(truth, given) or flat(truth) in flat(given))


def _outcome(raw: dict[str, Any]) -> dict[str, Any]:
    """A field outcome in one shape. The verified engine records `FieldOutcome` (state,
    observed_value, canonical_key); the legacy engine records each committed answer as
    ``{key, label, value, preserved}``."""
    if "state" in raw:
        return raw
    return {
        "label": raw.get("label") or "",
        "state": "preserved" if raw.get("preserved") else "verified_filled",
        "observed_value": raw.get("value") or "",
        "canonical_key": raw.get("key") or "",
        "answer_source": "",
    }


def grade(
    outcomes: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
    profile: Any = None,
    *,
    leftovers: list[dict[str, Any]] = (),
    required_empty: list[Any] = (),
) -> dict[str, Any]:
    """Each field outcome and leftover graded against the page and the profile, plus
    required controls the page showed empty that the fill never recorded.

    Grades: ``ok``; ``wrong_value`` (the page holds the fill's answer, but not the
    profile's); ``changed`` (the page shows something else); ``not_shown`` (empty on the
    page); ``rejected`` (invalid or a form message); ``not_seen`` (no readback row: a step
    without a snapshot or a label the readback words differently); ``blank_required`` /
    ``unanswered_optional`` / ``failed`` / ``manual_review`` for answers not given (a
    leftover is required when the fill listed its label as required and empty).
    """
    required = {
        flat_label(item if isinstance(item, str) else (item or {}).get("label", ""))
        for item in required_empty
    }
    # A question the resolver also gave up on is listed again with reason "needs_review";
    # it is graded once, under the filler's own reason.
    by_label: dict[str, dict[str, Any]] = {}
    for item in leftovers:
        if not isinstance(item, dict):
            continue
        key = flat_label(item.get("label") or "") or f"#{len(by_label)}"  # unlabelled: each its own
        if key in by_label and str(item.get("reason") or "") in {"", "needs_review"}:
            continue
        by_label[key] = {
            "label": item.get("label") or "", "state": "unanswered", "observed_value": "",
            "canonical_key": item.get("key") or "", "answer_source": str(item.get("reason") or ""),
            "required": key in required,
        }
    unanswered = list(by_label.values())
    listed = set(by_label)
    unanswered += [
        {"label": label, "state": "unanswered", "observed_value": "", "canonical_key": "",
         "answer_source": "required_empty", "required": True}
        for label in (
            i if isinstance(i, str) else (i or {}).get("label", "") for i in required_empty
        )
        if label and flat_label(label) not in listed
    ]
    rows = _rows(snapshots)
    graded, counts, recorded = [], Counter(), set()
    for outcome in [_outcome(o) for o in outcomes] + unanswered:
        label = str(outcome.get("label") or "")
        key = flat_label(label)
        recorded.add(key)
        state = str(outcome.get("state") or "")
        given = str(outcome.get("observed_value") or "")
        row = rows.get(key)
        if state in _HELD:
            if row is None:
                verdict = "not_seen"
            elif row.get("invalid") or row.get("message"):
                verdict = "rejected"
            elif not str(row.get("shown") or "").strip():
                verdict = "not_shown"
            elif given and not _same_answer(given, str(row["shown"])):
                verdict = "changed"
            else:
                truth = _truth(str(outcome.get("canonical_key") or ""), profile)
                wrong = truth and given and _contradicts(truth, given)
                verdict = "wrong_value" if wrong else "ok"
        elif state == "failed":
            verdict = "failed"
        elif state in {"manual_review", "ambiguous", "invalid_existing"}:
            verdict = "manual_review"
        else:
            verdict = "blank_required" if outcome.get("required") else "unanswered_optional"
        counts[verdict] += 1
        graded.append(
            {
                "label": label[:160],
                "key": outcome.get("canonical_key") or "",
                "state": state,
                "source": outcome.get("answer_source") or "",
                "kind": (row or {}).get("kind", ""),
                "given": given[:200],
                "shown": str((row or {}).get("shown") or "")[:200],
                "message": str((row or {}).get("message") or "")[:200],
                "grade": verdict,
            }
        )
    unseen = [
        {"label": row.get("label", "")[:160], "kind": row.get("kind", ""), "step": row.get("step")}
        for key, row in rows.items()
        if key not in recorded and row.get("required") and not str(row.get("shown") or "").strip()
    ]
    counts["blank_required_unrecorded"] = len(unseen)
    return {"counts": dict(counts), "fields": graded, "unrecorded_blank_required": unseen}


_CLOSED = re.compile(
    r"no longer|closed|not accepting|has been filled|position is unavailable|expired", re.I
)
_BOT = re.compile(
    r"captcha|robot|bot check|verify you are human|cloudflare|access denied|blocked", re.I
)
_SMS = re.compile(r"\bsms\b|text message|phone verification", re.I)
_SIGN_IN = re.compile(r"sign[ -]?in|log[ -]?in|password|create (an )?account", re.I)
_ALREADY = re.compile(r"already applied|already submitted", re.I)


def fill_end(measures: dict[str, Any], *, error: str = "", timed_out: bool = False) -> str:
    """Why the fill stopped, as one category."""
    if timed_out:
        return "timeout"
    if error:
        return "crash"
    if not measures:
        return "no_result"
    handoff = str(measures.get("handoff") or "")
    status = str(measures.get("status") or "")
    if status == "awaiting_otp":
        return "otp_unresolved"
    for name, pattern in (("closed", _CLOSED), ("already_applied", _ALREADY), ("bot_check", _BOT),
                          ("sms", _SMS), ("sign_in", _SIGN_IN)):
        if pattern.search(handoff):
            return name
    if measures.get("final_step_reached"):
        return "reached_review"
    if status == "fill_failed":
        return "fill_failed"
    if not measures.get("steps_reached") and not measures.get("committed"):
        return "no_form"
    return "stopped_mid"
