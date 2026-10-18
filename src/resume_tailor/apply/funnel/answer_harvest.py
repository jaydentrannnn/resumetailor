"""Answers the applicant typed on the page, saved to the Answer book.

A fill leaves some questions for the applicant (unanswered, ambiguous, invalid, or for
review). What they then type into those fields is the answer the next form asking the
same question should get, so it is collected:

- when Continue fill starts (`collect`, before the fill touches the tab),
- when the review snapshot is refreshed (`from_review`, inside `review._record`),
- every `_INTERVAL_S` seconds, and as soon as the tab's URL changes, on retained review
  tabs no fill is using (`watch`; the same pass sees a manual submission and closes the
  tab of a submitted or skipped application), and
- from a small listener installed on handoff (`LISTENER_JS`): Workday shows one step at a
  time, so a step the applicant already clicked past is only in what the listener saw.

Only questions the fill left are collected, never a field it answered (a change there is
a correction, `review.correct`). A question a profile field answers fills that field
when blank (`answer_memory.save_to_profile`); anything else is remembered with source
``page``. Passwords, files, credentials, consents and self-identification answers are
never collected (`answer_memory.storable`, `review._PROTECTED`). Values are never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from resume_tailor import config
from resume_tailor.apply.answers import answer_memory
from resume_tailor.apply.funnel import store, store_models

_log = logging.getLogger(__name__)

#: Field outcome states that mean "left for the applicant".
_LEFT = frozenset({"unanswered", "ambiguous", "invalid_existing", "manual_review", "failed"})
_SKIP_KINDS = frozenset({"file", "unsupported", "checkbox"})
_RETAINED = frozenset({"awaiting_review", "awaiting_otp", "submit_unconfirmed"})
#: Finished applications whose retained tab is closed (it holds a whole ATS page in memory).
_CLOSES_TAB = frozenset({"submitted", "skipped"})
_INTERVAL_S = 20.0
#: Tab URLs are polled this often, so a submission is seen as its confirmation page loads.
_TICK_S = 2.0
_CLOSE_GRACE_S = 30.0
_TIMEOUT_S = 20.0

#: Records what the applicant picks or types, by question label, in ``window.__rtTyped``.
LISTENER_JS = r"""
() => {
  window.__rtTyped = window.__rtTyped || {};
  if (window.__rtTypedInstalled) return true;
  window.__rtTypedInstalled = true;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const text = (el) => clean(el && (el.innerText || el.textContent));
  const groupOf = (el) => el.closest(
    '[data-automation-id^="formField-"], fieldset, [role="radiogroup"], [role="group"]');
  const groupLabel = (group) => {
    if (!group) return '';
    const by = group.getAttribute('aria-labelledby');
    if (by) {
      const t = clean(by.split(/\s+/).map((id) => text(document.getElementById(id))).join(' '));
      if (t) return t;
    }
    const head = group.querySelector('legend, label');
    return head ? text(head) : '';
  };
  const labelOf = (el) => {
    if (el.labels && el.labels.length) return text(el.labels[0]);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = clean(by.split(/\s+/).map((id) => text(document.getElementById(id))).join(' '));
      if (t) return t;
    }
    return clean(el.getAttribute('aria-label')) || groupLabel(groupOf(el));
  };
  const put = (label, value, kind) => {
    label = clean(label).slice(0, 500);
    value = clean(value).slice(0, 5000);
    if (label && value) window.__rtTyped[label] = { value, kind };
  };
  document.addEventListener('change', (event) => {
    const el = event.target;
    if (!el || !el.tagName) return;
    const type = (el.type || '').toLowerCase();
    if (['password', 'file', 'hidden', 'checkbox'].includes(type)) return;
    if (type === 'radio') {
      if (el.checked) put(groupLabel(groupOf(el)), labelOf(el), 'choice');
    } else if (el.tagName === 'SELECT') {
      const option = el.options[el.selectedIndex];
      put(labelOf(el), option ? option.text : '', 'choice');
    } else if (['INPUT', 'TEXTAREA'].includes(el.tagName)) {
      put(labelOf(el), el.value, 'text');
    }
  }, true);
  document.addEventListener('click', (event) => {
    const option = event.target && event.target.closest && event.target.closest('[role="option"]');
    if (!option) return;
    const owner = document.querySelector(
      '[aria-expanded="true"][aria-haspopup="listbox"], [aria-expanded="true"][role="combobox"]');
    if (owner) put(labelOf(owner), text(option), 'choice');
  }, true);
  return true;
}
"""
_READ_JS = "() => window.__rtTyped || {}"


@dataclass(frozen=True)
class Typed:
    """One answer seen on the page."""

    label: str
    value: str
    canonical_key: str = ""


# -- what to collect (pure) ---------------------------------------------------------------


def left_for_you(fill: store_models.FillResult) -> set[str]:
    """Normalized labels of the questions the fill left for the applicant."""
    labels: list[str] = [*fill.required_empty]
    labels += [
        str(item.get("label") or "") for item in fill.field_outcomes
        if isinstance(item, dict) and item.get("state") in _LEFT
    ]
    labels += [
        str(item.get("label") or "") if isinstance(item, dict) else str(item)
        for item in fill.leftovers
    ]
    return {norm for label in labels if (norm := answer_memory.normalize_label(label))}


def from_fields(fields: Iterable[Any]) -> list[Typed]:
    """Answers in scanned fields (`scanner.FieldObservation`)."""
    found = []
    for field in fields:
        if field.control_kind in _SKIP_KINDS or not field.current_value.strip():
            continue
        if field.control_kind == "combobox" and field.selection_state != "committed":
            continue
        found.append(Typed(field.label, field.current_value.strip(), field.canonical_key))
    return found


def from_listener(raw: Any) -> list[Typed]:
    """Answers the listener recorded (`LISTENER_JS`)."""
    if not isinstance(raw, dict):
        return []
    return [
        Typed(str(label), str(item.get("value") or "").strip())
        for label, item in raw.items()
        if isinstance(item, dict) and str(item.get("value") or "").strip()
    ]


def save(
    typed: Iterable[Typed], left: set[str], *, company: str = "", ats: str = ""
) -> int:
    """Save the answers to questions in ``left``; how many were saved."""
    from resume_tailor.apply.funnel import review  # noqa: PLC0415

    saved = 0
    seen: set[str] = set()
    for item in typed:
        norm = answer_memory.normalize_label(item.label)
        if norm not in left or norm in seen:
            continue
        seen.add(norm)
        if review._PROTECTED.search(item.label) or answer_memory.is_sensitive(item.label):
            continue
        try:
            key = answer_memory.profile_key(item.label, item.canonical_key)
            if key:
                saved += answer_memory.save_to_profile(key, item.value)
            elif _changed(item, company, ats):
                saved += answer_memory.remember(
                    item.label, item.value, company=company, ats=ats,
                    canonical_key=item.canonical_key, source="page",
                ) is not None
        except Exception:  # noqa: BLE001 - one odd field must not stop the rest
            _log.warning("could not save a typed answer", exc_info=True)
    return saved


def _changed(item: Typed, company: str, ats: str) -> bool:
    """Whether the book does not already hold this exact answer for this site."""
    norm = answer_memory.normalize_label(item.label, company)
    row = answer_memory._conn().execute(
        "SELECT answer FROM answer_memory WHERE kind = 'answer' AND label_norm = ? "
        "AND ats = ? AND options_digest = ''",
        (norm, (ats or "").lower()),
    ).fetchone()
    return row is None or str(row[0]).strip() != item.value


_NUMBER = re.compile(r"\d+")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_AMOUNT = re.compile(r"[$€£]?\s*(\d[\d,]*(?:\.\d+)?)\s*%?")
_PHONE = re.compile(r"[\d\s()+.-]+")


def _flat(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def _amount(text: str) -> float | None:
    found = _AMOUNT.fullmatch(text.strip())
    return float(found.group(1).replace(",", "")) if found else None


def _same_answer(given: str, shown: str) -> bool:
    """Whether the page still shows the fill's answer, written differently or not: case,
    spacing, punctuation, a phone's formatting, a number's ("3.70", "$90,000") or a date's
    order do not count. Each rule applies to its own kind of answer only, so "3.7" and
    "7.3" differ."""
    if _flat(given) == _flat(shown):
        return True
    if _PHONE.fullmatch(given) and _PHONE.fullmatch(shown):
        given_digits, shown_digits = re.sub(r"\D", "", given), re.sub(r"\D", "", shown)
        if len(given_digits) >= 7 and given_digits[-10:] == shown_digits[-10:]:
            return True
    amounts = _amount(given), _amount(shown)
    if None not in amounts:
        return amounts[0] == amounts[1]
    if not (_YEAR.search(given) and _YEAR.search(shown)):
        return False
    numbers = sorted(int(n) for n in _NUMBER.findall(given))
    return numbers == sorted(int(n) for n in _NUMBER.findall(shown)) and (
        re.sub(r"[^a-z]+", "", given.casefold()) == re.sub(r"[^a-z]+", "", shown.casefold())
    )


def corrections(fill: store_models.FillResult, fields: Iterable[Any]) -> list[dict[str, str]]:
    """Answers the fill gave that the page now shows changed, as ``{label, key}`` (never
    a value): the applicant corrected them. A blank or uncommitted field is not counted,
    nor a label asked more than once (two "Employer" rows): the fill's record and the
    page's fields share no identity, so a repeated label cannot be paired with its field."""
    fields = list(fields)
    asked = Counter(answer_memory.normalize_label(field.label) for field in fields)
    shown: dict[str, str] = {}
    for field in fields:
        value = str(getattr(field, "current_value", "") or "").strip()
        if not value or (field.control_kind == "combobox" and field.selection_state != "committed"):
            continue
        shown.setdefault(answer_memory.normalize_label(field.label), value)
    given_items = [
        item for item in fill.filled
        if isinstance(item, dict) and not item.get("preserved") and item.get("key") != "existing"
    ]
    answered = Counter(
        answer_memory.normalize_label(str(item.get("label") or "")) for item in given_items
    )
    found: list[dict[str, str]] = []
    for item in given_items:
        label = str(item.get("label") or "")
        norm = answer_memory.normalize_label(label)
        given = str(item.get("value") or "").strip()
        now = shown.get(norm)
        if not norm or asked[norm] > 1 or answered[norm] > 1 or not given or now is None:
            continue
        if not _same_answer(given, now):
            found.append({"label": label[:120], "key": str(item.get("key") or "")})
    return found


def _record_corrections(app: store_models.Application, found: list[dict[str, str]]) -> None:
    """Keep the latest corrections on the application's fill diagnostics."""
    if not app.fill:
        return
    fill = store_models.FillResult.model_validate(app.fill)
    if fill.diagnostics.get("corrections", []) == found:
        return
    fill.diagnostics = {**fill.diagnostics, "corrections": found}
    app.fill = fill
    store.upsert(app)


# -- reading the tab ----------------------------------------------------------------------


def from_review(
    app: store_models.Application, prior: store_models.FillResult, fields: Iterable[Any]
) -> int:
    """`review._record`'s hook: the refreshed fields against the fill's last outcome."""
    return save(from_fields(fields), left_for_you(prior), company=app.company, ats=_ats(app))


def _ats(app: store_models.Application) -> str:
    return (app.ats or "").lower()


async def _frames_typed(page: Any) -> list[Typed]:
    typed: list[Typed] = []
    for frame in page.frames:
        with contextlib.suppress(Exception):
            typed += from_listener(await frame.evaluate(_READ_JS))
    return typed


async def install(page: Any) -> None:
    """Install the listener in every frame of ``page`` (idempotent)."""
    for frame in page.frames:
        with contextlib.suppress(Exception):
            await frame.evaluate(LISTENER_JS)


async def _collect_async(application_id: str) -> int:
    from resume_tailor.apply.driver import browser, scanner  # noqa: PLC0415
    from resume_tailor.web import template_ops  # noqa: PLC0415

    with template_ops.LOCK:
        workspace_path = config.APPLICATIONS_PATH
        app = store.get(application_id)
    if app is None or not app.fill:
        return 0
    fill = store_models.FillResult.model_validate(app.fill)
    left = left_for_you(fill)
    if not fill.browser_target_id or (browser.extension_mode() and FILLING):
        return 0
    # Only an open tab: never start a browser just to read one.
    if fill.browser_target_id not in (browser.open_target_ids() or set()):
        return 0
    connection = (browser.async_cdp_browser(background=True) if browser.extension_mode()
                  else browser.async_cdp_browser())
    async with connection as connected:
        for context in connected.contexts:
            page = await browser.async_find_target(context, fill.browser_target_id)
            if page is None:
                continue
            from resume_tailor.apply.funnel import submission_monitor  # noqa: PLC0415
            if await submission_monitor.inspect(app, page, workspace_path=workspace_path):
                return 0
            observed = await scanner.scan(page)
            found = corrections(fill, observed.fields)
            typed = await _frames_typed(page) + from_fields(observed.fields) if left else []
            if left:
                await install(page)
            with template_ops.LOCK:
                if config.APPLICATIONS_PATH != workspace_path:
                    return 0
                current = store.get(application_id)
                if current is not None:
                    _record_corrections(current, found)
                return save(typed, left, company=app.company, ats=_ats(app)) if left else 0
    return 0


def collect(application_id: str) -> int:
    """Read the application's review tab and save what was typed; 0 on any failure.

    Runs on a worker thread with no event loop (as the fill workers are)."""
    try:
        return asyncio.run(asyncio.wait_for(_collect_async(application_id), _TIMEOUT_S))
    except Exception:  # noqa: BLE001 - a closed tab or browser is an expected state
        return 0


# -- the background pass over retained review tabs ----------------------------------------

_WATCH_LOCK = threading.Lock()
_WATCHED: set[str] = set()
#: Applications a fill is working on right now; their tabs are left alone.
FILLING: set[str] = set()
_THREAD: threading.Thread | None = None
_STOP = threading.Event()


def watch(application_id: str) -> None:
    """Collect from this application's review tab every `_INTERVAL_S` seconds while it
    waits for the applicant (starts the one background thread when needed)."""
    global _THREAD
    with _WATCH_LOCK:
        _WATCHED.add(application_id)
        if _THREAD is None:
            _STOP.clear()
            _THREAD = threading.Thread(target=_loop, name="answer-harvest", daemon=True)
            _THREAD.start()


def stop() -> None:
    """Stop the background pass (tests, shutdown)."""
    _STOP.set()


@dataclass
class _Pass:
    """What the loop remembers between ticks."""

    urls: dict[str, str]  # application id -> its tab's URL at the last tick
    closing: dict[str, float]  # application id -> when its finished tab is closed
    last_full: float


def _loop() -> None:
    global _THREAD
    state = _Pass(urls={}, closing={}, last_full=time.monotonic())
    while not _STOP.wait(_TICK_S):
        _tick(state)
        with _WATCH_LOCK:
            # Checked and cleared under one lock, so a `watch` racing this exit either
            # lands before it (and keeps the loop) or sees no thread and starts one.
            if not _WATCHED:
                _THREAD = None
                return
    with _WATCH_LOCK:
        _THREAD = None


def _tick(state: _Pass) -> None:
    """One cheap look at the tabs (one HTTP call); a tab is read when its URL changed —
    a submission's confirmation page — or on the `_INTERVAL_S` full pass."""
    from resume_tailor.apply.driver import browser  # noqa: PLC0415

    if browser.extension_mode() and FILLING:
        return  # the relay has one connection; fills take priority
    targets = browser.open_targets()
    if targets is None:
        return  # browser unreachable: try again later
    now = time.monotonic()
    full = now - state.last_full >= _INTERVAL_S
    if full:
        state.last_full = now
    with _WATCH_LOCK:
        watched = sorted(_WATCHED - FILLING)
    for application_id in watched:
        app = store.get(application_id)
        fill = store_models.FillResult.model_validate(app.fill) if app and app.fill else None
        target = fill.browser_target_id if fill else ""
        if app is not None and app.status in _CLOSES_TAB and target in targets:
            # Submitted or skipped: leave the confirmation in view briefly, then close.
            due = state.closing.setdefault(application_id, now + _CLOSE_GRACE_S)
            if now < due:
                continue
            browser.close_target(target)
        if app is None or app.status not in _RETAINED or target not in targets:
            with _WATCH_LOCK:
                _WATCHED.discard(application_id)
            state.urls.pop(application_id, None)
            state.closing.pop(application_id, None)
            continue
        url = targets[target]
        moved = state.urls.get(application_id, url) != url
        state.urls[application_id] = url
        if (full or moved) and collect(application_id):
            _log.info("saved typed answers for %s", application_id)


def restore() -> None:
    """Resume observation of this workspace's retained tabs after startup."""
    from resume_tailor.apply.driver import browser  # noqa: PLC0415

    with _WATCH_LOCK:
        _WATCHED.clear()
    open_ids: set[str] | None = None
    for app in store.load_all().values():
        if app.status not in _RETAINED | _CLOSES_TAB or not app.fill:
            continue
        fill = store_models.FillResult.model_validate(app.fill)
        if not fill.browser_target_id:
            continue
        if app.status in _CLOSES_TAB:
            # A finished application's tab left open across a restart is closed too.
            if open_ids is None:
                open_ids = browser.open_target_ids() or set()
            if fill.browser_target_id not in open_ids:
                continue
        watch(app.source_job_id)
