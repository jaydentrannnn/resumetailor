"""LLM-assisted micro-resolver for custom ATS comboboxes, floating listboxes, and validation blockers.

When the deterministic macro-pass leaves required fields empty, encounters non-standard
custom widgets (e.g. Workday/Ashby custom dropdowns), or hits a disabled 'Next' button
with on-page validation errors, this resolver extracts an accessibility snapshot of the
blockers, consults the LLM, and executes targeted actions.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Literal

from pydantic import BaseModel, Field

from resume_tailor import config
from resume_tailor.apply.answers.profile import ApplicantProfile
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.forms.field_matcher import match_option
from resume_tailor.apply.forms.field_types import ObservedOption
from resume_tailor.apply.funnel.packet import Packet
from resume_tailor.infra import llm

_log = logging.getLogger(__name__)


class FieldAction(BaseModel):
    """Targeted UI action chosen by the LLM to resolve a form blocker."""

    label: str = Field(description="Human label of the field or question")
    selector: str = Field(description="Target CSS selector on the page")
    action: Literal["select_combobox", "choose_radio", "check_options", "fill_text"]
    value: str = Field(
        description="Option text to choose or text value to fill; for check_options, the "
        "option texts to tick joined by ' | '",
    )
    rationale: str = Field(default="", description="Why this choice matches the candidate")


class StepResolution(BaseModel):
    """List of field actions to resolve the current page or step."""

    actions: list[FieldAction] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are an expert ATS form-filling assistant. You resolve unselected comboboxes, \
radio buttons, and validation errors in complex ATS forms (Workday, Ashby, Greenhouse) \
using ONLY the applicant's profile and resume data.

Rules:
- Never fabricate work authorization or citizenship: adhere strictly to the candidate's declared profile.
- For 'How did you hear about us?' or sources, pick 'Job Board', 'LinkedIn', 'Online', or 'Other' if exact text isn't listed.
- For demographic / EEO questions (Gender, Race, Veteran, Disability): if the applicant declined or preferred not to say, choose 'Decline to self-identify', 'I prefer not to say', or similar.
- For a checkbox group, use check_options and tick only options the profile supports (a location question: the applicant's location or stated relocation preferences). When none applies, tick the one explicit 'No', 'None of the above' or 'Not Available' option on its own.
- Return exactly one action for EVERY unresolved control, using its selector. When the \
profile does not answer a control, still return an action for it with value "unknown"; \
never leave a control out.
- A value must be one of that control's listed options, copied exactly (or "unknown").
"""

#: A decision the model returns when the profile does not answer a control.
_UNKNOWN = "unknown"


_INSPECT_PAGE_JS = """
() => {
  const isVisible = (el) => {
    if (!el || el.disabled) return false;
    const s = window.getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  const getLabel = (el) => {
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) return lbl.innerText.trim();
    }
    // Workday: the question lives in the form field's label/legend; the button's own
    // aria-label is only "<current value> Required".
    const wdField = el.closest('[data-automation-id^="formField-"]');
    if (wdField) {
      const title = wdField.querySelector('label, legend');
      if (title && title.innerText.trim()) return title.innerText.trim();
    }
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const labelledby = el.getAttribute('aria-labelledby');
    if (labelledby) {
      const ref = document.getElementById(labelledby);
      if (ref) return ref.innerText.trim();
    }
    const parentLabel = el.closest('label');
    if (parentLabel) return parentLabel.innerText.trim();
    const prompt = el.closest('[data-automation-id*="formField"], [data-automation-id*="Question"], .form-group');
    if (prompt) {
      const title = prompt.querySelector('label, [data-automation-id*="label"], legend, .field-label');
      if (title) return title.innerText.trim();
    }
    // Custom forms (Epic Games) put the question as bare text in an ancestor that holds
    // only this control; the widget's own "Select" placeholder is not part of it.
    let node = el.parentElement, text = '';
    for (let depth = 0; node && depth < 12; depth++, node = node.parentElement) {
      if (node.querySelectorAll('input:not([type="hidden"]), select, textarea').length > 1) break;
      const own = (node.innerText || '').replace(/[\\u2060\\u200b]/g, '').trim();
      const widget = (el.closest('[class*="-control"]')?.innerText || '').trim();
      const stripped = (widget && own.endsWith(widget) ? own.slice(0, -widget.length) : own).trim();
      if (stripped && !/^(select|enter)$/i.test(stripped)) text = stripped;
    }
    if (text) return text.replace(/\\s*\\*?\\s*:?\\s*$/, '').trim();
    return el.getAttribute('placeholder') || el.getAttribute('name') || '';
  };

  const uniqueSelector = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const autoid = el.getAttribute('data-automation-id');
    if (autoid) return `[data-automation-id="${CSS.escape(autoid)}"]`;
    const name = el.getAttribute('name');
    if (name) return `${el.tagName.toLowerCase()}[name="${name.replace(/"/g, '\\\\\\"')}"]`;
    return '';
  };

  const errors = [];
  document.querySelectorAll('[data-automation-id*="error" i], [role="alert"], .alert-danger, .field-error, [aria-invalid="true"]').forEach(el => {
    if (isVisible(el)) {
      const txt = el.innerText.trim();
      if (txt && txt.length < 200 && !errors.includes(txt)) errors.push(txt);
    }
  });

  // Upload widgets ("Select files" opens the OS file picker) and Workday multiselect
  // prompts (chip containers, search boxes; the fill runner owns those) are never
  // dropdowns, whatever their automation ids contain.
  const notADropdown = (el) => el.matches('input[type="file"]') || !!el.closest(
    // "file" only as a word part: "profile…" containers hold real dropdowns.
    '[data-automation-id^="file" i], [data-automation-id*="-file" i], [data-automation-id*="file-" i], ' +
    '[data-automation-id*="upload" i], [data-automation-id*="attachment" i], ' +
    '[class*="dropzone" i], [class*="drop-zone" i], [class*="file-upload" i], ' +
    '[data-automation-id="multiselectInputContainer"], [data-automation-id="multiSelectContainer"], ' +
    '[data-automation-id="selectedItemList"]'
  );
  const fieldKey = (el) => {
    const field = el.closest('[data-automation-id^="formField-"]');
    return field ? field.getAttribute('data-automation-id') : null;
  };
  const invalid = (el) => el.getAttribute('aria-invalid') === 'true' || !!el.closest('[data-automation-id^="formField-"]')
    ?.querySelector('[aria-invalid="true"], [data-automation-id="errorMessage"], [data-automation-id="inputAlert"]');

  const unresolved = [];
  const seenFields = new Set();

  // 1. Custom comboboxes / dropdown buttons (real popup triggers only)
  // React Select inputs do not always carry role=combobox (Epic Games' form).
  document.querySelectorAll('[role="combobox"], [aria-haspopup="listbox"], input[id^="react-select-"][id$="-input"]').forEach(el => {
    if (isVisible(el) && !notADropdown(el)) {
      // One question per Workday form field, however many triggers it renders.
      const key = fieldKey(el);
      if (key && seenFields.has(key)) return;
      let current = el.innerText.trim();
      if (!current && el.value) current = el.value.trim();
      const singleVal = el.closest('.select__control, [class*="-control"]')?.querySelector('.select__single-value, [class*="-singleValue"]');
      if (singleVal) current = singleVal.innerText.trim();

      const label = getLabel(el);
      const sel = uniqueSelector(el);
      if (sel && (!current || current.toLowerCase().includes('select') || current.toLowerCase().includes('choose'))) {
        if (key) seenFields.add(key);
        unresolved.push({
          type: 'combobox',
          selector: sel,
          label: label || 'Dropdown selection',
          current: current,
          invalid: invalid(el)
        });
      }
    }
  });

  // 2. Unchecked required radio button groups
  const radioNames = new Set();
  document.querySelectorAll('input[type="radio"]').forEach(r => {
    if (r.name && !radioNames.has(r.name) && isVisible(r)) {
      radioNames.add(r.name);
      const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${r.name}"]`));
      const anyChecked = group.some(g => g.checked);
      if (!anyChecked) {
        const label = getLabel(r) || r.name;
        const options = group.map(g => getLabel(g) || g.value);
        unresolved.push({
          type: 'radiogroup',
          selector: `input[type="radio"][name="${r.name}"]`,
          label: label,
          options: options,
          invalid: group.some(invalid)
        });
      }
    }
  });

  // 2b. Required checkbox groups with nothing ticked (Workday "-CheckboxGroup" fieldsets:
  // MPC's internship locations, American Century's "listed firms" with a "No" option).
  document.querySelectorAll('fieldset[data-automation-id$="-CheckboxGroup"]').forEach(group => {
    const boxes = Array.from(group.querySelectorAll('input[type="checkbox"]'));
    if (!boxes.length || boxes.some(b => b.checked) || !boxes.some(isVisible)) return;
    const required = group.getAttribute('aria-required') === 'true'
      || boxes.some(b => b.getAttribute('aria-required') === 'true');
    if (!required) return;
    const title = group.closest('[data-automation-id^="formField-"]')?.querySelector('legend');
    unresolved.push({
      type: 'checkboxgroup',
      selector: `[data-automation-id="${CSS.escape(group.getAttribute('data-automation-id'))}"]`,
      label: title ? title.innerText.trim() : 'Checkbox group',
      options: boxes.map(b => getLabel(b)),
      invalid: invalid(group)
    });
  });

  // 3. Check if Next / Continue button is currently disabled
  let advanceDisabled = false;
  const nextBtn = Array.from(document.querySelectorAll('button')).find(b => {
    const t = b.innerText.trim().toLowerCase();
    return (t === 'next' || t === 'continue' || t === 'save & continue') && isVisible(b);
  });
  if (nextBtn) {
    advanceDisabled = nextBtn.disabled || nextBtn.getAttribute('aria-disabled') === 'true';
  }

    return {
    errors: errors,
    unresolved: unresolved.slice(0, 30),
    advance_disabled: advanceDisabled
  };
}
"""


def extract_page_blockers(page: Any) -> dict[str, Any]:
    """Inspect the page for validation errors and unresolved custom controls."""
    try:
        data = page.evaluate(_INSPECT_PAGE_JS)
        if isinstance(data, dict):
            return data
    except Exception as exc:  # noqa: BLE001
        _log.debug("error inspecting page blockers: %s", exc)
    return {"errors": [], "unresolved": [], "advance_disabled": False}


#: True for a file-upload control or anything inside one: clicking it opens the OS picker.
UPLOAD_WIDGET_JS = r"""(el) => el.matches('input[type="file"]') || !!el.closest(
  '[data-automation-id^="file" i], [data-automation-id*="-file" i], [data-automation-id*="file-" i], ' +
  '[data-automation-id*="upload" i], [data-automation-id*="attachment" i], ' +
  '[class*="dropzone" i], [class*="drop-zone" i], [class*="file-upload" i]')"""


def _is_upload_widget(locator: Any) -> bool:
    try:
        return locator.evaluate(UPLOAD_WIDGET_JS) is True
    except Exception:  # noqa: BLE001 - an unreadable control is not clicked blind either
        return True


def _option_match(options: list[str], target_value: str, *, key: str = "") -> str | None:
    """Choose one observed option; aliases never permit a partial-text match."""
    observed = [ObservedOption(option_id=str(index), label=label, value=label) for index, label in enumerate(options)]
    result = match_option(observed, target_value, key=key)
    return options[int(result.option_id)] if result.status == "matched" else None


def _menu_choices(page: Any, trigger: Any) -> list[Any]:
    menu_id = trigger.get_attribute("aria-controls") or trigger.get_attribute("aria-owns")
    if menu_id:
        menu = page.locator(f"[id='{menu_id}']")
        if menu.count() > 0:
            return menu.locator("[role='option'], .select__option, [data-automation-id*='promptOption']").all()
    visible_menus = page.locator("[role='listbox']:visible, [class*='-menu']:visible")
    if visible_menus.count() != 1:
        return []
    return visible_menus.first.locator("[role='option'], .select__option, [data-automation-id*='promptOption']").all()


def _select_combobox_option(
    page: Any, trigger_selector: str, target_value: str, *, key: str = "", phone_region: str = "",
) -> bool:
    """Click a custom combobox trigger and pick the matching option from the popup portal."""
    try:
        trigger = page.locator(trigger_selector).first
        if trigger.count() == 0 or not trigger.is_visible() or _is_upload_widget(trigger):
            return False

        tag_name = trigger.evaluate("el => el.tagName.toLowerCase()")
        is_input = tag_name == "input"

        before = _selected_combobox_text(trigger)
        if key != "phone_country_code" and before and _option_match([before], target_value, key=key):
            return True
        clicks.safe_click(trigger, purpose="select", timeout=3000)
        search_terms = [""]
        if key == "phone_country_code" and phone_region:
            search_terms.extend([phone_region, target_value])
        else:
            search_terms.extend(field_matcher.search_terms(key, target_value))
        match = None
        for term in search_terms:
            if term:
                search_box = trigger if is_input else page.locator(
                    "input[data-automation-id='searchBox'], input[role='searchbox'], input[placeholder*='search' i]"
                ).first
                if search_box.count() == 0 or not search_box.is_visible():
                    continue
                search_box.fill(term)
            for _ in range(8 if term else 1):
                choices = [choice for choice in _menu_choices(page, trigger) if choice.is_visible()]
                option_texts = [choice.inner_text().strip() for choice in choices]
                if key == "phone_country_code":
                    chosen_text = _phone_option(option_texts, target_value, phone_region)
                    if not chosen_text:
                        chosen_text = _option_match(option_texts, target_value, key=key)
                else:
                    chosen_text = field_matcher.closest_option(option_texts, target_value, key=key)
                if chosen_text:
                    match = next(choice for choice in choices if choice.inner_text().strip() == chosen_text)
                    break
                if term:
                    page.wait_for_timeout(250)
            if match is not None:
                break
        if match is None:
            trigger.press("Escape")
            return False
        if key == "phone_country_code" and match.get_attribute("aria-selected") == "true":
            trigger.press("Escape")
            return True
        selected_option = match.inner_text().strip()
        clicks.safe_click(match, purpose="select", timeout=3000)
        page.wait_for_timeout(150)
        selected = _selected_combobox_text(trigger)
        # Some widgets (Workday listbox buttons) repaint their text a few hundred ms later.
        for _ in range(8):
            if key == "phone_country_code" or _norm(selected) == _norm(selected_option):
                break
            page.wait_for_timeout(250)
            selected = _selected_combobox_text(trigger)
        if key == "phone_country_code":
            # React Select often detaches the clicked option when its menu closes.
            # Reopen the owned menu and inspect the newly rendered committed choice.
            clicks.safe_click(trigger, purpose="select", timeout=3000)
            refreshed = [choice for choice in _menu_choices(page, trigger) if choice.is_visible()]
            labels = [choice.inner_text().strip() for choice in refreshed]
            committed_label = _phone_option(labels, target_value, phone_region) or _option_match(
                labels, target_value, key=key,
            )
            committed = bool(committed_label) and any(
                choice.inner_text().strip() == committed_label
                and choice.get_attribute("aria-selected") == "true"
                for choice in refreshed
            )
            trigger.press("Escape")
            return committed and _norm(selected) == _norm(target_value)
        return _norm(selected) == _norm(selected_option) and _norm(selected) != _norm(before)
    except Exception as exc:  # noqa: BLE001
        _log.debug("combobox selection failed: %s", exc)
        with contextlib.suppress(Exception):
            trigger.press("Escape")
        return False


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w+]+", " ", value.casefold())).strip()


def _selected_combobox_text(trigger: Any) -> str:
    """React Select keeps its chosen value in a sibling, not in the search input."""
    with contextlib.suppress(Exception):
        selected = trigger.evaluate(
            "el => el.closest('.select__control, [class*=-control]')?.querySelector('.select__single-value, [class*=-singleValue]')?.textContent || ''"
        )
        if isinstance(selected, str) and selected.strip():
            return selected.strip()
    with contextlib.suppress(Exception):
        if trigger.get_attribute("role") == "combobox":
            return ""
    return str(trigger.inner_text() or "").strip()


def _phone_option(options: list[str], code: str, region: str) -> str | None:
    """Resolve a calling-code menu only when the declared phone region disambiguates it."""
    region_aliases = {
        "us": "united states", "usa": "united states", "united states of america": "united states",
        "ca": "canada", "gb": "united kingdom", "uk": "united kingdom",
    }
    region_key = region_aliases.get(_norm(region), _norm(region))
    if not region_key or not re.fullmatch(r"\+\d{1,4}", code):
        return None
    code_pattern = re.compile(rf"(?<!\d){re.escape(code)}(?!\d)")
    matches = [
        option for option in options
        if code_pattern.search(option)
        and region_aliases.get(_norm(code_pattern.sub("", option)), _norm(code_pattern.sub("", option))) == region_key
    ]
    return matches[0] if len(matches) == 1 else None


def _choose_radio_option(page: Any, radio_selector: str, target_value: str) -> bool:
    """Select the radio button matching target_value."""
    target_lower = _norm(target_value)
    try:
        radios = page.locator(radio_selector).all()
        for r in radios:
            # Check associated label
            rid = r.get_attribute("id")
            text = ""
            if rid:
                lbl = page.locator(f"label[for='{rid}']").first
                if lbl.count() > 0:
                    text = lbl.inner_text()
            if not text:
                text = r.get_attribute("value") or ""
            if target_lower == _norm(text):
                clicks.safe_click(r, purpose="select", timeout=3000)
                return True
    except Exception as exc:  # noqa: BLE001
        _log.debug("radio selection failed: %s", exc)
    return False


#: A checkbox-group option that answers "none of these"; it is never ticked with another.
_EXCLUSIVE_OPTION = re.compile(r"^(?:no|none(?: of the above)?|not available|n/?a)$", re.I)


def checked_values(value: str) -> list[str]:
    """The option texts a check_options action names (joined by ``|``)."""
    return [part.strip() for part in value.split("|") if part.strip()]


def _check_options(page: Any, group_selector: str, values: list[str]) -> bool:
    """Tick the checkboxes labelled ``values`` in one group; True when all are ticked."""
    wanted = {_norm(value) for value in values}
    ticked = 0
    try:
        for box in page.locator(f"{group_selector} input[type='checkbox']").all():
            bid = box.get_attribute("id")
            label = page.locator(f"label[for='{bid}']").first if bid else None
            if label is None or label.count() == 0 or _norm(label.inner_text()) not in wanted:
                continue
            if not box.is_checked():
                clicks.safe_click(label, purpose="select", timeout=3000)
                page.wait_for_timeout(150)
            ticked += box.is_checked()
    except Exception as exc:  # noqa: BLE001
        _log.debug("checkbox selection failed: %s", exc)
        return False
    return ticked == len(wanted)


def execute_action(page: Any, action: FieldAction) -> bool:
    """Execute one resolved action in the browser page."""
    if action.action == "select_combobox":
        return _select_combobox_option(page, action.selector, action.value)
    if action.action == "choose_radio":
        return _choose_radio_option(page, action.selector, action.value)
    if action.action == "check_options":
        return _check_options(page, action.selector, checked_values(action.value))
    if action.action == "fill_text":
        try:
            loc = page.locator(action.selector).first
            if loc.count() > 0 and loc.is_visible():
                loc.fill(action.value)
                page.wait_for_timeout(300)
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


class SkillPick(BaseModel):
    skill: str = Field(description="The applicant's skill, exactly as given")
    option: str | None = Field(description="The one listed option naming the same skill, or null")


class SkillPicks(BaseModel):
    picks: list[SkillPick] = Field(default_factory=list)


_SKILLS_SYSTEM_PROMPT = """\
You match a job applicant's own skills to the options a job application's Skills search \
returned. For each skill you get the options its search showed.

Pick the option that names the SAME skill: a synonym, a spelling or wording variant, the \
full name for an abbreviation or the reverse, or the skill with a qualifier that does not \
change it (for example "Python" -> "Python (Programming Language)", "ML" -> "Machine \
Learning").

Return null when no option names the same skill. Never pick a broader, narrower, or merely \
related skill ("Python" -> "Django" is wrong, "Machine Learning" -> "Deep Learning" is \
wrong): the form would then claim a skill the applicant did not list. Copy the chosen \
option's text exactly.
"""


def choose_skill_options(
    unmatched: dict[str, list[str]], *, deadline: float | None = None,
) -> dict[str, str | None]:
    """One model call for every skill whose search had no exact option.

    The model sees only skill names and option labels (plain strings). Its answers are
    kept only when they are one of the options that skill's own search showed.
    """
    if not unmatched:
        return {}
    client = llm.client_for("answer")
    if deadline is not None:
        timeout = max(1.0, min(60.0, deadline - time.monotonic()))
        if hasattr(client, "timeout"):
            client.timeout = min(float(client.timeout), timeout)
        elif hasattr(client, "with_options"):
            client = client.with_options(timeout=timeout)
    payload = [{"skill": skill, "options": options} for skill, options in unmatched.items()]
    response = client.messages.parse(
        model=config.model_for("answer"),
        max_tokens=config.max_tokens_for("answer"),
        system=_SKILLS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"<skills>\n{json.dumps(payload, indent=2)}\n</skills>"}],
        output_format=SkillPicks,
    )
    parsed: SkillPicks = response.parsed_output
    chosen: dict[str, str | None] = {skill: None for skill in unmatched}
    for pick in parsed.picks:
        options = unmatched.get(pick.skill)
        if options is not None and pick.option in options:
            chosen[pick.skill] = pick.option
    return chosen


#: Extra model rounds per call for questions the model's own answers revealed; they do
#: not count against ``max_retries``.
_MAX_REVEAL_ROUNDS = 2


@dataclass
class StepLedger:
    """What one form step has already been through, so a retry touches only the gaps.

    Keyed by selector. A control whose options were read is not opened again; one the
    model was already asked about (answered or not) is not sent again on this step.
    """

    options: dict[str, list[str]] = dc_field(default_factory=dict)
    asked: set[str] = dc_field(default_factory=set)
    done: set[str] = dc_field(default_factory=set)
    #: Model calls a control was sent in; one the model skipped is sent once more.
    tries: dict[str, int] = dc_field(default_factory=dict)
    model_unavailable: bool = False


#: Bump when `_SYSTEM_PROMPT` or the payload changes: cached choices are keyed on it.
_RESOLVER_PROMPT_VERSION = "resolver-v1"
#: Model calls one control may be sent in before it is left for the applicant. The
#: prompt asks for a decision per control; a control the model still leaves out is sent
#: once more, alone.
_MAX_ASKS = 2
#: Guards `_IN_FLIGHT` and the cache file's read-modify-write (held only briefly).
_CHOICES_LOCK = threading.Lock()
#: Choice keys a tab is asking the model about right now. Another tab showing the same
#: question waits for that answer instead of asking again; unrelated questions never wait.
_IN_FLIGHT: dict[str, threading.Event] = {}
#: Longest a tab waits for another tab's answer to the same question.
_IN_FLIGHT_WAIT = 30.0


def _choices_path() -> Any:
    return config.CACHE_DIR / "resolver-choices.json"


def _choice_key(field: dict[str, Any], profile_digest: str) -> str:
    """Identity of one choice question: the same question, options, applicant and model
    get the same answer on every posting and every run (parallel tabs included)."""
    options = sorted(_norm(str(option)) for option in field.get("options") or [])
    payload = "\n".join([
        _RESOLVER_PROMPT_VERSION, config.fingerprint("answer"), profile_digest,
        str(field.get("type") or ""), _norm(str(field.get("label") or "")), *options,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_choices() -> dict[str, dict[str, str]]:
    try:
        data = json.loads(_choices_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_choices(new: dict[str, dict[str, str]]) -> None:
    """Merge ``new`` into the cache file (read-modify-write under `_CHOICES_LOCK`)."""
    if not new:
        return
    with _CHOICES_LOCK, contextlib.suppress(OSError):
        path = _choices_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = _read_choices() | new
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _remembered(keys: dict[str, str], observed: dict[str, dict[str, Any]]) -> list[FieldAction]:
    """Choices already made for these very questions (another tab, an earlier run), as
    actions on this page's selectors; one whose option this form does not list is skipped."""
    known = _read_choices()
    hits = []
    for selector, key in keys.items():
        hit = known.get(key)
        if not isinstance(hit, dict) or not hit.get("action") or not hit.get("value"):
            continue
        with contextlib.suppress(Exception):
            action = FieldAction(
                label=str(observed[selector].get("label") or ""), selector=selector,
                action=hit["action"], value=hit["value"], rationale="same question, same answer",
            )
            if _usable(action, observed[selector]):
                hits.append(action)
    return hits


def _usable(action: FieldAction, field: dict[str, Any] | None) -> bool:
    """Whether ``action`` answers ``field`` with one of the options the form rendered."""
    if field is None or field.get("phone_code_menu"):
        return False
    offered = {_norm(str(value)) for value in field.get("options", [])}
    if action.action in {"select_combobox", "choose_radio"} and _norm(action.value) not in offered:
        return False
    if action.action == "fill_text" or action.action == "select_combobox" and field.get("type") != "combobox":
        return False
    if action.action == "check_options":
        picked = checked_values(action.value)
        return not (
            field.get("type") != "checkboxgroup" or not picked
            or any(_norm(value) not in offered for value in picked)
            or len(picked) > 1 and any(_EXCLUSIVE_OPTION.match(value) for value in picked)
        )
    return field.get("type") != "checkboxgroup"


def resolve_step_blockers(
    page: Any,
    packet: Packet,
    profile: ApplicantProfile,
    *,
    max_retries: int = 2,
    on_progress: Callable[[str], None] | None = None,
    deadline: float | None = None,
    ledger: StepLedger | None = None,
    only_invalid: bool = False,
) -> bool:
    """Identify page blockers / errors and call the LLM to resolve them.

    With a ``ledger``, controls already resolved or already put to the model on this step
    are skipped, so a stuck field does not send the whole page round again. With
    ``only_invalid`` (after a rejected advance), only the fields the form marks invalid
    are retried, when it marks any.

    Returns True if blockers were found and resolved, False if no blockers or resolution failed.
    """
    return _StepResolver(
        page,
        packet,
        profile,
        max_retries=max_retries,
        on_progress=on_progress,
        deadline=deadline,
        ledger=ledger if ledger is not None else StepLedger(),
        only_invalid=only_invalid,
    ).run()


class _StepResolver:
    """One `resolve_step_blockers` call: rounds of look at the page → answer → apply."""

    def __init__(
        self,
        page: Any,
        packet: Packet,
        profile: ApplicantProfile,
        *,
        max_retries: int,
        on_progress: Callable[[str], None] | None,
        deadline: float | None,
        ledger: StepLedger,
        only_invalid: bool,
    ) -> None:
        self.page = page
        self.packet = packet
        self.profile = profile
        self.max_retries = max_retries
        self.on_progress = on_progress
        self.deadline = deadline
        self.ledger = ledger
        self.only_invalid = only_invalid
        self.attempt = 0
        self.reveal_rounds = 0
        # Set after an answer reveals follow-up questions: the next round covers only those.
        self.revealed: set[str] | None = None

    def log(self, msg: str) -> None:
        if self.on_progress:
            self.on_progress(f"[hybrid-resolver] {msg}")

    def run(self) -> bool:
        while self.revealed is not None or self.attempt < self.max_retries:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                return False
            if self.revealed is None:
                self.attempt += 1
            outcome = self._round()
            if outcome is not None:
                return outcome
        return False

    def _round(self) -> bool | None:
        """One look at the page and one answer pass: a bool ends the call, None goes
        round again."""
        ledger = self.ledger
        info = extract_page_blockers(self.page)
        errors = info.get("errors") or []
        unresolved = info.get("unresolved") or []
        advance_disabled = bool(info.get("advance_disabled"))
        present = {str(f.get("selector")) for f in unresolved}

        if not errors and not unresolved and not advance_disabled:
            return True

        seen_before, unresolved = self._still_open(unresolved)
        if seen_before and unresolved:
            self.log(
                f"retrying {len(unresolved)} unfilled field(s): "
                + ", ".join(str(f.get("label") or "field")[:40] for f in unresolved)
            )
        if not unresolved:
            # Every remaining blocker was already put to the model on this step; the
            # applicant resolves it, not another full pass.
            if seen_before:
                self.log(f"{len(seen_before)} field(s) still need input; leaving them for review")
            return not errors and not advance_disabled

        self._load_options(unresolved)
        unresolved = self._select_phone_codes(unresolved)
        reserved = [
            f for f in unresolved
            if re.search(
                r"salary|compensation|race|ethnic|hispanic|latino",
                str(f.get("label") or ""), re.I,
            )
        ]
        ledger.asked |= {str(f.get("selector")) for f in reserved}  # never the model's to answer
        unresolved = [f for f in unresolved if f not in reserved]
        if not unresolved:
            # Validation errors alone give the model nothing it may act on.
            return not errors and not advance_disabled

        self.log(
            f"attempt {self.attempt}: found {len(unresolved)} unresolved controls, "
            f"{len(errors)} errors"
        )
        answered = self._answer(unresolved, errors)
        if answered is None:
            return False
        actions, responded, observed = answered
        if not actions:
            if not responded:
                self.log("LLM returned no actions")
            return None
        executed = self._execute(actions)
        return self._after_actions(executed, present, observed)

    def _still_open(
        self, unresolved: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """(blockers this step already handled, the ones still to work on)."""
        handled = self.ledger.asked | self.ledger.done
        seen_before = [f for f in unresolved if str(f.get("selector")) in handled]
        unresolved = [f for f in unresolved if str(f.get("selector")) not in handled]
        if self.revealed is not None:
            # Not marked invalid yet: the form validates them only on Save and Continue.
            unresolved = [f for f in unresolved if str(f.get("selector")) in self.revealed]
            self.revealed = None
        elif self.only_invalid and any(f.get("invalid") for f in unresolved):
            unresolved = [f for f in unresolved if f.get("invalid")]
        return seen_before, unresolved

    def _load_options(self, unresolved: list[dict[str, Any]]) -> None:
        """Only let the model choose from options actually rendered by this form."""
        page, ledger = self.page, self.ledger
        for field in unresolved:
            if field.get("type") != "combobox" or not field.get("selector"):
                continue
            selector = str(field["selector"])
            if selector in ledger.options:
                field["options"] = ledger.options[selector]
                continue
            try:
                trigger = page.locator(selector).first
                if _is_upload_widget(trigger):
                    field["options"] = []
                    continue
                clicks.safe_click(trigger, purpose="select", timeout=3000)
                choices = _menu_choices(page, trigger)
                all_options = [
                    choice.inner_text().strip() for choice in choices if choice.is_visible()
                ]
                trigger.press("Escape")
            except Exception:  # noqa: BLE001
                all_options = []
            field["options"] = all_options[:50]
            ledger.options[selector] = field["options"]

    def _select_phone_codes(self, unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Answer phone calling-code menus from the profile; the rest stay unresolved."""
        profile = self.profile
        for field in unresolved:
            options = field.get("options") or []
            field["phone_code_menu"] = (
                sum(bool(re.search(r"\+\d{1,4}\b", str(o))) for o in options) >= 2
            )
            if field["phone_code_menu"]:
                field["phone_match"] = _phone_option(
                    [str(o) for o in options], profile.phone_country_code,
                    profile.phone_country_region,
                )

        resolved_phone: set[str] = set()
        for field in unresolved:
            if field.get("phone_code_menu") and field.get("phone_match"):
                selected = _select_combobox_option(
                    self.page, str(field["selector"]), profile.phone_country_code,
                    key="phone_country_code", phone_region=profile.phone_country_region,
                )
                if selected:
                    resolved_phone.add(str(field["selector"]))
                    self.log(f"selected phone calling code for {field.get('label')}")
        self.ledger.done |= resolved_phone
        return [field for field in unresolved if str(field.get("selector")) not in resolved_phone]

    # -- answering ---------------------------------------------------------------------

    def _answer(
        self, unresolved: list[dict[str, Any]], errors: list[Any]
    ) -> tuple[list[FieldAction], set[str], dict[str, dict[str, Any]]] | None:
        """(actions to apply, selectors the model answered, the controls by selector);
        None when the model call failed."""
        ledger = self.ledger
        safe_profile = self.profile.model_dump(
            exclude={"workday_password", "workday_email"},
            mode="json",
        )
        profile_digest = hashlib.sha256(
            json.dumps(safe_profile, sort_keys=True).encode("utf-8")
        ).hexdigest()
        observed = {str(item.get("selector")): item for item in unresolved if item.get("selector")}
        keys = {
            selector: _choice_key(field, profile_digest) for selector, field in observed.items()
        }

        actions, answered = self._recall(keys, observed)
        if actions:
            self.log(f"reusing {len(actions)} earlier answer(s) to the same question(s)")
        to_ask = [field for field in unresolved if str(field.get("selector")) not in answered]
        asked = self._ask_model(to_ask, errors, keys, observed, safe_profile)
        if asked is None:
            return None
        model_actions, responded = asked

        # A control the model decided on (an option, "unknown", or an option the form does
        # not list) is final on this step; one it left out entirely goes into the next,
        # smaller call, up to `_MAX_ASKS` calls.
        answered |= responded
        for field in to_ask:
            selector = str(field.get("selector") or "")
            if selector:
                ledger.tries[selector] = ledger.tries.get(selector, 0) + 1
        ledger.asked |= {
            selector for selector in observed
            if selector in answered or ledger.tries.get(selector, 0) >= _MAX_ASKS
        }
        actions += model_actions
        return actions, responded, observed

    def _recall(
        self, keys: dict[str, str], observed: dict[str, dict[str, Any]]
    ) -> tuple[list[FieldAction], set[str]]:
        """Earlier answers to these questions, waiting briefly for any another tab is
        asking about right now."""
        actions = _remembered(keys, observed)
        answered = {action.selector for action in actions}
        # A question another tab is asking right now: wait for its answer rather than ask
        # the same thing twice (parallel fills of one employer's postings, 2026-09).
        with _CHOICES_LOCK:
            waiting = {
                selector: _IN_FLIGHT[key] for selector, key in keys.items()
                if selector not in answered and key in _IN_FLIGHT
            }
        if waiting:
            wait_until = time.monotonic() + _IN_FLIGHT_WAIT
            if self.deadline is not None:
                wait_until = min(wait_until, self.deadline - 5)
            for event in set(waiting.values()):
                event.wait(max(0.0, wait_until - time.monotonic()))
            actions = _remembered(keys, observed)
            answered = {action.selector for action in actions}
        return actions, answered

    def _ask_model(
        self,
        to_ask: list[dict[str, Any]],
        errors: list[Any],
        keys: dict[str, str],
        observed: dict[str, dict[str, Any]],
        safe_profile: dict[str, Any],
    ) -> tuple[list[FieldAction], set[str]] | None:
        """Put `to_ask` to the model while marking those questions in flight; (usable
        actions, selectors it answered), or None when the call failed."""
        mine: dict[str, threading.Event] = {}
        with _CHOICES_LOCK:
            for field in to_ask:
                key = keys[str(field.get("selector"))]
                if key not in _IN_FLIGHT:
                    mine[key] = _IN_FLIGHT[key] = threading.Event()
        model_actions: list[FieldAction] = []
        responded: set[str] = set()
        try:
            if to_ask:
                resolution = self._call_model(to_ask, errors, safe_profile)
                if resolution is None:
                    return None
                asked_now = {str(field.get("selector")) for field in to_ask}
                responded = {
                    action.selector for action in resolution.actions
                    if action.selector in asked_now
                }
                unknown = sorted(
                    str(observed[action.selector].get("label") or action.selector)[:40]
                    for action in resolution.actions
                    if action.selector in asked_now and _norm(action.value) == _UNKNOWN
                )
                if unknown:
                    self.log(
                        f"the profile does not answer {len(unknown)} question(s): "
                        f"{', '.join(unknown)}"
                    )
                model_actions = [
                    action for action in resolution.actions
                    if action.selector in asked_now
                    and _usable(action, observed.get(action.selector))
                ]
                _write_choices({
                    keys[action.selector]: {
                        "action": action.action, "value": action.value,
                        "label": str(observed[action.selector].get("label") or "")[:200],
                    }
                    for action in model_actions
                    if action.action in {"select_combobox", "choose_radio", "check_options"}
                })
        finally:
            with _CHOICES_LOCK:
                for key, event in mine.items():
                    _IN_FLIGHT.pop(key, None)
                    event.set()
        return model_actions, responded

    def _call_model(
        self, to_ask: list[dict[str, Any]], errors: list[Any], safe_profile: dict[str, Any]
    ) -> StepResolution | None:
        user_content = [
            f"<unresolved_controls>\n{json.dumps(to_ask, indent=2)}\n</unresolved_controls>",
            f"<validation_errors>\n{json.dumps(errors, indent=2)}\n</validation_errors>",
            f"<candidate_profile>\n{json.dumps(safe_profile, indent=2)}\n</candidate_profile>",
            f"<packet_fields>\n{json.dumps(self.packet.fields, indent=2)}\n</packet_fields>",
        ]
        try:
            client = llm.client_for("answer")
            if self.deadline is not None:
                timeout = max(1.0, min(60.0, self.deadline - time.monotonic()))
                if hasattr(client, "timeout"):
                    client.timeout = min(float(client.timeout), timeout)
                elif hasattr(client, "with_options"):
                    client = client.with_options(timeout=timeout)
            response = client.messages.parse(
                model=config.model_for("answer"),
                max_tokens=config.max_tokens_for("answer"),
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": "\n\n".join(user_content)}],
                output_format=StepResolution,
            )
            resolution: StepResolution = response.parsed_output
            return resolution
        except llm.LLMError as exc:
            status = re.search(r"\bHTTP (429|5\d\d)\b", str(exc))
            if status:
                self.ledger.model_unavailable = True
                self.log(
                    f"Autofill model unavailable (HTTP {status.group(1)}); leaving "
                    f"{len(to_ask)} question(s) for review"
                )
            else:
                self.log(f"LLM call failed: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            self.log(f"LLM call failed: {exc}")
            return None

    # -- applying ----------------------------------------------------------------------

    def _execute(self, actions: list[FieldAction]) -> int:
        executed = 0
        for action in actions:
            self.log(f"executing action: {action.action} on '{action.label}' -> '{action.value}'")
            ok = execute_action(self.page, action)
            if not ok:
                # A choice that did not stick (a list still opening, a repaint) is
                # retried once rather than left blank on this tab only.
                self.page.wait_for_timeout(500)
                ok = execute_action(self.page, action)
            if ok:
                executed += 1
                self.ledger.done.add(action.selector)

        self.log(f"successfully applied {executed}/{len(actions)} actions")
        self.page.wait_for_timeout(1000)
        return executed

    def _after_actions(
        self, executed: int, present: set[str], observed: dict[str, dict[str, Any]]
    ) -> bool | None:
        """True once the step's blockers are gone; None to go round again."""
        ledger = self.ledger
        updated = extract_page_blockers(self.page)
        # An answer can reveal a follow-up ("If hired, can you provide proof of
        # eligibility?" after "legally permitted to work" = Yes). Workday shows no error
        # for it until Save and Continue, so look for it here rather than stop early.
        known = present | ledger.asked | ledger.done
        new = {
            str(f.get("selector")) for f in updated.get("unresolved") or []
            if f.get("selector") and str(f.get("selector")) not in known
        }
        if executed and new and self.reveal_rounds < _MAX_REVEAL_ROUNDS:
            self.reveal_rounds += 1
            self.revealed = new
            self.log(f"answer revealed {len(new)} new question(s)")
            return None
        skipped = [
            f for f in updated.get("unresolved") or []
            if str(f.get("selector")) in observed
            and str(f.get("selector")) not in ledger.asked | ledger.done
        ]
        if skipped and self.attempt < self.max_retries:
            # The page shows no error yet, but a question the model skipped is still
            # blank: ask about it again rather than call the step cleared.
            return None
        if not updated.get("advance_disabled") and not updated.get("errors"):
            self.log("validation blockers cleared!")
            return True
        return None
