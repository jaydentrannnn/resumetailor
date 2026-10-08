"""Workday dropdowns and listboxes: reading, picking an option, and filling a step's dropdowns."""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.answers import questions, salary
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher

from . import workday_skills

# -- My Information / questionnaire dropdowns -------------------------------------------

#: Workday single-select dropdowns: a ``button[aria-haspopup=listbox]`` whose
#: ``aria-controls`` names a ``ul[role=listbox]`` of ``li[role=option]``.
DROPDOWNS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const labelOf = b => {
    if (b.id) {
      const l = document.querySelector(`label[for="${CSS.escape(b.id)}"]`);
      if (l) return (l.innerText || '').trim();
    }
    const field = b.closest("[data-automation-id^='formField-']");
    const l = field && field.querySelector('label, legend');
    return l ? (l.innerText || '').trim() : (b.getAttribute('aria-label') || '');
  };
  return [...document.querySelectorAll("button[aria-haspopup='listbox']")]
    .filter(b => vis(b) && b.closest("[data-automation-id='applyFlowPage']"))
    .filter(b => !b.closest("[data-automation-id='utilityButtonBar']"))
    .map(b => ({
      selector: b.id ? `#${CSS.escape(b.id)}` : '',
      label: labelOf(b).replace(/\*\s*$/, '').trim(),
      help: (b.getAttribute('aria-describedby') || '').split(/\s+/)
        .map(id => document.getElementById(id)?.textContent || '').join(' ').trim(),
      current: (b.innerText || '').trim(),
      required: /\*\s*$/.test(labelOf(b)) ||
        /\bRequired\b/.test(b.getAttribute('aria-label') || ''),
    }))
    .filter(item => item.selector);
}"""

_PLACEHOLDER = re.compile(r"^\s*(select one|select|choose one|--)\s*$", re.I)

def dropdowns(page: Any) -> list[dict[str, Any]]:
    try:
        found = page.evaluate(DROPDOWNS_JS)
    except Exception:  # noqa: BLE001
        return []
    return [item for item in found or [] if isinstance(item, dict)]

_OPTIONS_JS = r"""(id) => {
  const list = document.getElementById(id);
  if (!list) return null;
  return [...list.querySelectorAll("[role='option']")].map(o => ({
    id: o.id, label: (o.innerText || '').trim(),
    disabled: o.getAttribute('aria-disabled') === 'true',
  }));
}"""

def _pick_listbox_option(options: list[dict[str, Any]], value: str, key: str) -> tuple[str, str] | None:
    """(label, id) of the one option meaning ``value``, or None."""
    from resume_tailor.apply.answers.widget_actions import _option_match  # noqa: PLC0415

    usable = [o for o in options if not o["disabled"] and not _PLACEHOLDER.match(o["label"])]
    if key in {SALARY_RANGE_KEY, ANY_OPTION_KEY}:
        labels = [o["label"] for o in usable]
        chosen = salary.pick_range(labels, value) if key == SALARY_RANGE_KEY else any_option(labels, value)
        return (chosen, next(o["id"] for o in usable if o["label"] == chosen)) if chosen else None
    # "Bachelor of Science (B.S)" is matched on its name; the abbreviation is decoration.
    bare = [re.sub(r"\s*\([^)]*\)\s*$", "", o["label"]) for o in usable]
    chosen = _option_match([o["label"] for o in usable], value, key=key)
    if not chosen:
        by_bare = _option_match(bare, value, key=key)
        if by_bare and bare.count(by_bare) == 1:
            chosen = usable[bare.index(by_bare)]["label"]
    if not chosen:
        return None
    return chosen, next(o["id"] for o in usable if o["label"] == chosen)

#: What the last `select_listbox` call saw: its options and why it did not commit, so a
#: failed required choice is reported with the form's own wording (CACI's veteran list,
#: 2026-09, failed with nothing but its label in ``required_empty``).
last_listbox: dict[str, Any] = {}

def _options_text(options: list[str], limit: int = 8) -> str:
    shown = [option[:80] for option in options[:limit]]
    return " | ".join(shown) + (f" | … ({len(options) - limit} more)" if len(options) > limit else "")

def choice_failure(label: str, value: str, options: list[str], status: str = "no_match") -> str:
    """One review line for a profile fact no option named: the value, why, and the options."""
    seen = f"; options: {_options_text(options)}" if options else "; no options were read"
    return f"{label}: no option for {value} ({status.replace('_', ' ')}{seen})"

def select_listbox(page: Any, selector: str, value: str, *, key: str = "") -> bool:
    """Commit one option of a Workday listbox button, verified by the button's new text.

    Options are read in a single evaluate (country lists have ~250 entries, all rendered)
    and matched with the same exact/alias rules as every other choice
    (`field_matcher.match_option`). Workday updates the button text a few hundred ms
    after the click, so the result is polled rather than read once.
    """
    trigger = page.locator(selector).first
    last_listbox.clear()
    last_listbox.update(selector=selector, value=value, options=[], status="not_opened")
    try:
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        options = None
        for _ in range(12):
            # Workday sets aria-controls only once the list has opened, so it is re-read.
            list_id = trigger.get_attribute("aria-controls") or ""
            options = page.evaluate(_OPTIONS_JS, list_id) if list_id else None
            if options:
                break
            page.wait_for_timeout(250)
        labels = [str(o.get("label") or "") for o in options or [] if not _PLACEHOLDER.match(str(o.get("label") or ""))]
        last_listbox.update(options=labels, status="no_match" if labels else "no_options")
        picked = _pick_listbox_option(options or [], value, key)
        if picked is None:
            trigger.press("Escape")
            return False
        last_listbox["status"] = "unverified"
        chosen, option_id = picked
        last_listbox["chosen"] = chosen
        clicks.safe_click(page.locator(f"[id='{option_id}']").first, purpose="select", timeout=3000)
        for _ in range(12):
            if (trigger.inner_text() or "").strip() == chosen:
                return True
            page.wait_for_timeout(250)
        return False
    except Exception:  # noqa: BLE001 - an unverified choice is left for review
        with contextlib.suppress(Exception):
            trigger.press("Escape")
        return False

def _same_option(current: str, value: str, key: str) -> bool:
    """True when a committed option already means ``value`` (e.g. "United States of America")."""
    from resume_tailor.apply.answers.widget_actions import _option_match  # noqa: PLC0415

    return _option_match([current], value, key=key) is not None

def key_for_label(label: str) -> str | None:
    """The fact a question label asks for (`questions.classify`, shared by every fill)."""
    match = questions.classify(questions.Question(label))
    return match.key if match else None

def country_mismatch(page: Any, fields: dict[str, str]) -> str | None:
    """The Country dropdown's current text when it disagrees with the profile, else None.

    Checked again just before a step advances: Live Oak's and Upbound's Country read
    "Vietnam" (the account's saved address, 2026-09) after the fill, although the choice
    commits correctly when made — so the step is re-checked, not trusted.
    """
    value = fields.get("country", "")
    if not value:
        return None
    for item in dropdowns(page):
        if key_for_label(item["label"]) != "country":
            continue
        current = str(item.get("current") or "")
        if current and not _PLACEHOLDER.match(current) and not _same_option(current, value, "country"):
            return current
    return None

#: Keys these passes leave alone on purpose: salary is a per-posting answer, and the
#: phone code has its own step (`ensure_phone_code`). A salary *range* dropdown is the
#: exception (`salary_range_spec`).
_BLANK_EXEMPT = frozenset({"salary_expectation", "phone_country_code"})

#: The key a select call carries for a range dropdown; its value is a `salary.range_spec`.
SALARY_RANGE_KEY = "salary_range"

#: The key a select call carries for "any reasonable option" (`_ANY_OPTION_KEYS`).
ANY_OPTION_KEY = "any_option"

#: Questions whose exact answer the applicant does not mind: when no option names the
#: profile's answer, any reasonable option beats leaving a required field blank.
_ANY_OPTION_KEYS = frozenset({"how_heard"})

_OTHER_OPTION = re.compile(r"^other\b", re.I)

def any_option(options: list[str], value: str) -> str | None:
    """The option naming ``value`` ("LinkedIn" in "Social Media - LinkedIn"), else the
    first starting with "Other", else the first option."""
    wanted = field_matcher.normalize(value)
    usable = [
        text for text in dict.fromkeys(options) if text and not workday_skills._NO_ITEMS.match(text)
    ]
    return (
        next((t for t in usable if wanted and wanted in field_matcher.normalize(t)), None)
        or next((t for t in usable if _OTHER_OPTION.match(t)), None)
        or (usable[0] if usable else None)
    )

def salary_range_spec(label: str, fields: dict[str, str]) -> str | None:
    """The applicant's range for a salary question, in the unit it asks for (else the
    posting's default unit), or None when the profile has no salary range.

    The top is the precomputed answer (``min(posted top, applicant top)``,
    `salary.salary_fields`); the bottom is the applicant's own minimum, capped by it.
    """
    unit = salary.question_unit(label)
    prefix = {"hour": "salary_hourly", "year": "salary_yearly"}.get(unit or "", "salary_expectation")
    top = fields.get(f"{prefix}_number", "")
    if not top:
        return None
    if unit is None:
        unit = "hour" if fields.get(prefix, "").endswith("/hour") else "year"
    low = fields.get(f"{prefix}_low_number") or top
    try:
        return salary.range_spec(float(low), float(top), unit)
    except ValueError:
        return None

def _note_blank(blank: list[dict[str, str]] | None, key: str, label: str, unanswered: bool) -> None:
    """Record an unanswered control whose profile fact is empty."""
    if blank is not None and unanswered:
        blank.append({"key": key, "label": label})

def fill_dropdowns(
    page: Any,
    fields: dict[str, str],
    *,
    select: Callable[..., bool],
    progress: Callable[[str], None] = lambda _msg: None,
    deadline: float | None = None,
    review: list[str] | None = None,
    blank: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Select known profile facts in Workday dropdowns; return what was committed.

    A blank dropdown whose label maps to a profile fact the profile leaves empty is
    recorded in ``blank`` (`fill._missing_profile`), not skipped silently.

    Blank ("Select One") dropdowns only — except Country, which Workday pre-fills from
    the browser locale rather than from the applicant, and which re-renders the whole
    name/address block, so it is corrected first. A dropdown whose label does not map
    to a profile fact, or whose options have no unique match, is left for the resolver.
    """
    committed: list[dict[str, Any]] = []
    tried: set[str] = set()
    facts = questions.facts_for(fields)
    for _pass in range(3):
        progressed = False
        items = dropdowns(page)
        items.sort(key=lambda item: 0 if key_for_label(item["label"]) == "country" else 1)
        for item in items:
            if deadline is not None and time.monotonic() >= deadline:
                return committed
            selector = item["selector"]
            if selector in tried:
                continue
            question = questions.Question(item["label"], kind="choice",
                                          help_text=str(item.get("help") or ""))
            match = questions.classify(question)
            key = match.key if match else None
            answers = questions.answers(match, question, facts)
            value = answers[0] if answers else ""
            current = str(item.get("current") or "")
            is_blank = not current or bool(_PLACEHOLDER.match(current))
            spec = salary_range_spec(item["label"], fields) if key == "salary_expectation" else None
            if spec and is_blank:
                # A dropdown of pay ranges ("Select the range that best matches your
                # expectations", American Century 2026-09): the range covering the
                # applicant's own. A dropdown that lists no ranges matches nothing.
                tried.add(selector)
                if select(page, selector, spec, key=SALARY_RANGE_KEY):
                    chosen = str(last_listbox.get("chosen") or spec)
                    progress(f"Workday: selected {item['label'][:60]} = {chosen}")
                    committed.append({"key": key, "label": item["label"], "value": chosen, "selector": selector})
                    progressed = True
                continue
            if not key or key in _BLANK_EXEMPT:
                continue
            if not value:
                _note_blank(blank, questions.profile_field(key), item["label"], is_blank)
                continue
            if not is_blank and not (key == "country" and not _same_option(current, value, key)):
                continue
            tried.add(selector)
            for candidate in answers:
                if select(page, selector, candidate, key=key):
                    progress(f"Workday: selected {item['label']} = {candidate}")
                    committed.append(
                        {"key": key, "label": item["label"], "value": candidate, "selector": selector}
                    )
                    progressed = True
                    break
            else:
                if is_blank and key in _ANY_OPTION_KEYS and select(page, selector, value, key=ANY_OPTION_KEY):
                    chosen = str(last_listbox.get("chosen") or value)
                    progress(f"Workday: no exact option for {item['label']} = {value}; chose {chosen}")
                    committed.append({"key": key, "label": item["label"], "value": chosen, "selector": selector})
                    progressed = True
            if key == "country" and not progressed and review is not None:
                # A wrong country re-labels every name/address field and empties the
                # phone code; it must not pass silently.
                review.append(
                    f"Country: no option matching {value}" if is_blank
                    else f"Country is {current}; profile says {value}"
                )
                progress(f"Workday: could not change Country from {current or 'blank'} to {value}")
            elif not progressed and is_blank:
                # A profile fact no option named is a gap with a cause, not a bare label.
                # Always in the log; a review line only for self-identification, which the
                # resolver does not answer from the profile (other keys it often fills).
                seen = last_listbox if last_listbox.get("selector") == selector else {}
                line = choice_failure(item["label"], value, list(seen.get("options") or []),
                                      str(seen.get("status") or "no_match"))
                progress(f"Workday: {line}")
                if review is not None and key in field_matcher.EEO_KEYS:
                    review.append(line)
            if progressed and key == "country":
                page.wait_for_timeout(800)  # the form re-renders under the new country
                break
        if not progressed:
            break
    return committed
