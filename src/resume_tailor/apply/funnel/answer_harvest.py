"""Answers the applicant typed on the page, saved to the Answer book.

A fill leaves some questions for the applicant (unanswered, ambiguous, invalid, or for
review). What they then type into those fields is the answer the next form asking the
same question should get, so it is collected:

- when Continue fill starts (`collect`, before the fill touches the tab),
- when the review snapshot is refreshed (`from_review`, inside `review._record`),
- every `_INTERVAL_S` seconds on retained review tabs no fill is using (`watch`), and
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
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from resume_tailor.apply.answers import answer_memory
from resume_tailor.apply.funnel import store, store_models

_log = logging.getLogger(__name__)

#: Field outcome states that mean "left for the applicant".
_LEFT = frozenset({"unanswered", "ambiguous", "invalid_existing", "manual_review", "failed"})
_SKIP_KINDS = frozenset({"file", "unsupported", "checkbox"})
_RETAINED = frozenset({"awaiting_review", "awaiting_otp"})
_INTERVAL_S = 20.0
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

    app = store.get(application_id)
    if app is None or not app.fill:
        return 0
    fill = store_models.FillResult.model_validate(app.fill)
    left = left_for_you(fill)
    if not left or not fill.browser_target_id or browser.extension_mode():
        return 0
    # Only an open tab: never start a browser just to read one.
    if fill.browser_target_id not in (browser.open_target_ids() or set()):
        return 0
    async with browser.async_cdp_browser() as connected:
        for context in connected.contexts:
            page = await browser.async_find_target(context, fill.browser_target_id)
            if page is None:
                continue
            observed = await scanner.scan(page)
            typed = await _frames_typed(page) + from_fields(observed.fields)
            await install(page)
            return save(typed, left, company=app.company, ats=_ats(app))
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
    from resume_tailor.apply.driver import browser  # noqa: PLC0415

    if browser.extension_mode():
        return  # the relay has one connection, which fills need
    with _WATCH_LOCK:
        _WATCHED.add(application_id)
        if _THREAD is None:
            _STOP.clear()
            _THREAD = threading.Thread(target=_loop, name="answer-harvest", daemon=True)
            _THREAD.start()


def stop() -> None:
    """Stop the background pass (tests, shutdown)."""
    _STOP.set()


def _loop() -> None:
    global _THREAD
    from resume_tailor.apply.driver import browser  # noqa: PLC0415

    while not _STOP.wait(_INTERVAL_S):
        open_ids = browser.open_target_ids()
        with _WATCH_LOCK:
            watched = sorted(_WATCHED - FILLING)
        if open_ids is None:
            continue  # browser unreachable: try again later
        for application_id in watched:
            app = store.get(application_id)
            fill = store_models.FillResult.model_validate(app.fill) if app and app.fill else None
            if app is None or app.status not in _RETAINED or fill is None or (
                fill.browser_target_id not in open_ids
            ):
                with _WATCH_LOCK:
                    _WATCHED.discard(application_id)
                continue
            if collect(application_id):
                _log.info("saved typed answers for %s", application_id)
        with _WATCH_LOCK:
            if not _WATCHED:
                break
    with _WATCH_LOCK:
        _THREAD = None
