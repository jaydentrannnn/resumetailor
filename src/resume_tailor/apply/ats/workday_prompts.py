"""Workday prompt (search-and-pick) widgets and the phone country-code prompt."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.answers import questions
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher

from . import workday_dropdowns, workday_page, workday_skills

# -- Multiselect prompts (Field of Study, School, ...) -----------------------------------
_PROMPT_STATE_JS = r"""(id) => {
  const input = document.getElementById(id);
  const field = input && input.closest("[data-automation-id^='formField-']");
  if (!field) return null;
  return [...field.querySelectorAll("[data-automation-id='selectedItem']")]
    .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim());
}"""

#: Options of the open prompt popup; committed chips elsewhere (the phone code's
#: "United States of America (+1)") also carry ``promptOption`` and are not choices.
_OPEN_PROMPT_OPTIONS = (
    "[data-automation-id='promptOption']:not([data-automation-id='selectedItem'] *)"
)

def select_prompt(page: Any, input_id: str, value: str, *, key: str = "") -> bool:
    """Commit ``value`` in a Workday prompt: search, then click the one matching option.

    Searches run from the full value to shorter terms (`field_matcher.search_terms`:
    Workday finds "University of California, Irvine" from "Irvine", not from the full
    name), and the option is chosen by `field_matcher.closest_option`. A clicked option
    that opens a category ("Other" under a hierarchical source list) gets one drill-down
    pick. An existing chip is the applicant's answer: it counts only if it already matches.
    """
    def _means(chip: str, chosen: str) -> bool:
        return chip.strip() == chosen.strip() or field_matcher.closest_option([chip], value, key=key) is not None

    def _open_options() -> tuple[Any, list[str]]:
        options = page.locator(_OPEN_PROMPT_OPTIONS)
        return options, [str(text).strip() for text in options.all_inner_texts()]

    def _choose(texts: list[str]) -> str | None:
        # One leaf can sit under two categories ("LinkedIn" under Job Board and under
        # Social Media); identical labels are the same answer, not an ambiguity.
        unique = list(
            dict.fromkeys(
                text for text in texts if text and not workday_skills._NO_ITEMS.match(text)
            )
        )
        return field_matcher.closest_option(unique, value, key=key) if unique else None

    try:
        chips = page.evaluate(_PROMPT_STATE_JS, input_id)
        if chips is None:
            return False
        if chips:
            return len(chips) == 1 and field_matcher.closest_option(chips, value, key=key) is not None
        box = page.locator(f"[id='{input_id}']").first
        chosen = None
        for term in field_matcher.search_terms(key, value):
            box.fill("", timeout=3000)
            box.fill(term, timeout=3000)
            box.press("Enter")
            for _ in range(16):
                page.wait_for_timeout(250)
                # Enter on a search with a single result commits it without listing it
                # (Upbound's Field of Study: "Computer Science" -> "Computer and
                # Information Science"); the chip is then the answer to check.
                auto = page.evaluate(_PROMPT_STATE_JS, input_id) or []
                if auto:
                    return len(auto) == 1 and field_matcher.closest_option(auto, value, key=key) is not None
                options, texts = _open_options()
                chosen = _choose(texts)
                if chosen:
                    clicks.safe_click(options.nth(texts.index(chosen)), purpose="select", timeout=3000)
                    break
            if chosen:
                break
        if not chosen:
            box.press("Escape")
            return False

        def committed() -> bool | None:
            for _ in range(8):
                page.wait_for_timeout(250)
                chips = page.evaluate(_PROMPT_STATE_JS, input_id) or []
                if len(chips) == 1:
                    return _means(chips[0], chosen)
            return None

        verdict = committed()
        if verdict is not None:
            return verdict
        options, after = _open_options()
        leaf = _choose(after)
        if leaf and leaf != chosen:
            # The click opened a category ("Other" in a hierarchical source list).
            clicks.safe_click(options.nth(after.index(leaf)), purpose="select", timeout=3000)
            chosen = leaf
        else:
            # A single-select prompt (Field of Study) paints its chip once the list closes.
            with contextlib.suppress(Exception):
                box.press("Escape")
        return bool(committed())
    except Exception:  # noqa: BLE001 - an unverified prompt is left for review
        return False

def select_prompt_any(page: Any, input_id: str, value: str, *, max_depth: int = 3) -> str | None:
    """Commit *some* option of a (hierarchical) prompt; the committed chip, or None.

    Cencora's "How Did You Hear About Us?" (2026-09) lists sources only under categories,
    so no search finds "LinkedIn" as a choice. The list is opened unfiltered and, at each
    level, `any_option` is clicked; a category opens its children, a leaf commits.
    """
    def pick(texts: list[str]) -> str | None:
        return workday_dropdowns.any_option(texts, value)

    def read_options(previous: list[str] | None) -> tuple[Any, list[str]]:
        options, texts = page.locator(_OPEN_PROMPT_OPTIONS), []
        for _ in range(12):
            texts = [str(text).strip() for text in options.all_inner_texts()]
            if pick(texts) and texts != previous:
                break
            page.wait_for_timeout(250)
        return options, texts

    try:
        if page.evaluate(_PROMPT_STATE_JS, input_id):
            return None
        box = page.locator(f"[id='{input_id}']").first
        box.fill("", timeout=3000)
        clicks.safe_click(box, purpose="select", timeout=3000)
        options, texts = read_options(None)
        if not pick(texts):
            box.press("Enter")  # tenants that list only after a (blank) search
            options, texts = read_options(None)
        for _level in range(max_depth):
            choice = pick(texts)
            if not choice:
                break
            clicks.safe_click(options.nth(texts.index(choice)), purpose="select", timeout=3000)
            for _ in range(8):
                page.wait_for_timeout(250)
                chips = page.evaluate(_PROMPT_STATE_JS, input_id) or []
                if chips:
                    return str(chips[0]) if len(chips) == 1 else None
                if [str(t).strip() for t in options.all_inner_texts()] != texts:
                    break  # a category opened its children
            options, texts = read_options(texts)
        box.press("Escape")
    except Exception:  # noqa: BLE001 - an unverified prompt is left for review
        pass
    return None

#: Empty-or-not multiselect prompts on the current step, outside the My Experience rows
#: (those belong to ``workday_repeaters``) and the phone code (``ensure_phone_code``).
PROMPTS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  return [...document.querySelectorAll("[data-automation-id^='formField-']")]
    .filter(f => vis(f) && f.closest("[data-automation-id='applyFlowPage']"))
    .filter(f => f.querySelector("[data-automation-id='multiselectInputContainer']"))
    .filter(f => f.getAttribute('data-automation-id') !== 'formField-countryPhoneCode')
    .map(f => {
      const input = f.querySelector('input');
      const l = f.querySelector('label, legend');
      return {
        input_id: input ? input.id : '',
        field: f.getAttribute('data-automation-id'),
        label: (l ? l.innerText : '').replace(/\*\s*$/, '').trim(),
        chips: f.querySelectorAll("[data-automation-id='selectedItem']").length,
      };
    })
    .filter(p => p.input_id && !/^(workExperience|education|language)-/.test(p.input_id));
}"""

def fill_prompts(
    page: Any,
    fields: dict[str, str],
    *,
    select: Callable[..., bool] | None = None,
    select_any: Callable[..., str | None] | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> list[dict[str, Any]]:
    """Commit known profile facts in empty prompts ("How Did You Hear About Us?").

    A prompt that already holds a chip is the applicant's answer and is left alone; one
    whose label maps to no profile fact, or whose search finds no exact option, is left
    for review — except a source question (`_ANY_OPTION_KEYS`), which takes the closest
    available option (`select_prompt_any`).
    """
    choose = select or select_prompt
    choose_any = select_any or select_prompt_any
    try:
        found = page.evaluate(PROMPTS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    for item in found:
        if not isinstance(item, dict) or item.get("chips") or workday_skills.is_skills_prompt(item):
            continue
        question = questions.Question(str(item.get("label") or ""), kind="typeahead")
        match = questions.classify(question)
        key = match.key if match else None
        answers = questions.answers(match, question, questions.facts_for(fields))
        value = answers[0] if answers else ""
        if not key or not value:
            continue
        for candidate in answers:
            if choose(page, item["input_id"], candidate, key=key):
                progress(f"Workday: selected {item['label']} = {candidate}")
                committed.append({
                    "key": key, "label": item["label"], "value": candidate,
                    "selector": f"[id='{item['input_id']}']",
                })
                break
        else:
            chip = (
                choose_any(page, item["input_id"], value)
                if key in workday_dropdowns._ANY_OPTION_KEYS
                else None
            )
            if chip:
                progress(f"Workday: no exact option for {item['label']} = {value}; chose {chip}")
                committed.append({
                    "key": key, "label": item["label"], "value": chip,
                    "selector": f"[id='{item['input_id']}']",
                })
            else:
                progress(f"Workday: no exact option for {item['label']} = {value}; left for review")
    return committed

# -- Phone country code (multiselect prompt) --------------------------------------------
PHONE_CODE_JS = r"""() => {
  const field = document.querySelector("[data-automation-id='formField-countryPhoneCode']");
  if (!field) return null;
  const chips = [...field.querySelectorAll("[data-automation-id='selectedItem']")]
    .map(e => (e.innerText || e.getAttribute('aria-label') || '').trim());
  const input = field.querySelector('input');
  return {chips, input_id: input ? input.id : ''};
}"""

def ensure_phone_code(
    page: Any,
    region: str,
    code: str,
    *,
    progress: Callable[[str], None] = lambda _msg: None,
) -> bool | None:
    """Make the phone-code prompt hold exactly ``<region> (<code>)``.

    Returns None when the step has no such prompt, True when the committed chip matches,
    False when it could not be verified (left for review).
    """
    from resume_tailor.apply.answers.hybrid_resolver import _phone_option  # noqa: PLC0415

    try:
        state = page.evaluate(PHONE_CODE_JS)
    except Exception:  # noqa: BLE001
        return None
    if not state:
        return None

    def _matches(chip: str) -> bool:
        # The whole region name must agree: "United States Minor Outlying Islands (+1)"
        # also contains "United States" and "+1", and made the choice ambiguous.
        return _phone_option([chip], code, region) is not None

    chips = state.get("chips") or []
    if len(chips) == 1 and _matches(chips[0]):
        return True
    if not region or not code or not state.get("input_id"):
        return False
    field = page.locator("[data-automation-id='formField-countryPhoneCode']")
    try:
        for _ in chips:
            charm = field.locator("[data-automation-id='DELETE_charm']")
            if not workday_page._visible(charm):
                break
            clicks.safe_click(charm.first, purpose="select", timeout=3000)
            page.wait_for_timeout(200)
        box = page.locator(f"[id='{state['input_id']}']")
        box.fill(region, timeout=3000)
        box.press("Enter")
        options = page.locator("[data-automation-id='promptOption']")
        for _ in range(12):
            page.wait_for_timeout(250)
            texts = [str(t).strip() for t in options.all_inner_texts()]
            exact = [i for i, text in enumerate(texts) if _matches(text)]
            if len(exact) == 1:
                clicks.safe_click(options.nth(exact[0]), purpose="select", timeout=3000)
                break
        else:
            box.press("Escape")
            return False
        page.wait_for_timeout(300)
        after = page.evaluate(PHONE_CODE_JS) or {}
        ok = len(after.get("chips") or []) == 1 and _matches(after["chips"][0])
        if ok:
            progress(f"Workday: phone country code set to {after['chips'][0]}")
        return ok
    except Exception:  # noqa: BLE001
        return False
