"""Workday's Skills prompt: entering each skill as a chip and removing duplicates."""

from __future__ import annotations

import contextlib
import re
import time
from collections.abc import Callable
from typing import Any

from resume_tailor.apply.driver import clicks

from . import workday_page, workday_prompts

# -- Skills (multi-chip prompt) ----------------------------------------------------------
_SKILLS_LABEL = re.compile(r"^(?:type to add )?skills?$", re.I)

#: Workday's empty-search row, which is not a choice.
_NO_ITEMS = re.compile(r"^no (?:items|results|matches)(?: found)?\.?$", re.I)

def is_skills_prompt(item: dict[str, Any]) -> bool:
    return item.get("field") == "formField-skills" or bool(_SKILLS_LABEL.match(str(item.get("label") or "").strip()))

def _chips(page: Any, input_id: str) -> list[str]:
    try:
        return [
            str(chip) for chip in page.evaluate(workday_prompts._PROMPT_STATE_JS, input_id) or []
        ]
    except Exception:  # noqa: BLE001
        return []

#: Tag the ``index``-th committed chip of one prompt (the order `_chips` reads) with
#: ``data-rt-chip`` so it can be focused by attribute; False when there is no such chip.
_CHIP_AT_JS = r"""([id, index]) => {
  document.querySelectorAll('[data-rt-chip]').forEach(e => e.removeAttribute('data-rt-chip'));
  const input = document.getElementById(id);
  const field = input && input.closest("[data-automation-id^='formField-']");
  const chips = field ? [...field.querySelectorAll("[data-automation-id='selectedItem']")] : [];
  if (chips[index]) chips[index].setAttribute('data-rt-chip', '1');
  return !!chips[index];
}"""

def remove_duplicate_chips(page: Any, input_id: str, progress: Callable[[str], None] = lambda _msg: None) -> int:
    """Delete repeated chips (same skill text), keeping the first of each; the count removed.

    Workday refuses the whole step with "You cannot enter duplicate skills", and a draft
    saved by an earlier run keeps them (F5, 2026-09). A chip is removed the way its own
    label says ("press delete to clear value"), and each removal is verified.
    """
    from resume_tailor.apply.forms.field_matcher import same_skill_in  # noqa: PLC0415

    removed = 0
    for _ in range(20):
        chips = _chips(page, input_id)
        duplicate = next((index for index, chip in enumerate(chips) if same_skill_in(chips[:index], chip)), None)
        if duplicate is None or not _remove_chip(page, input_id, duplicate):
            break
        removed += 1
        progress(f"Workday: removed a duplicate skill chip ({chips[duplicate]})")
    return removed

def _remove_chip(page: Any, input_id: str, index: int) -> bool:
    """Delete the ``index``-th chip of one prompt; True when exactly one chip went."""
    before = len(_chips(page, input_id))
    try:
        if not page.evaluate(_CHIP_AT_JS, [input_id, index]):
            return False
        chip = page.locator("[data-rt-chip]").first
        chip.focus(timeout=2000)
        chip.press("Delete", timeout=2000)
        page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001 - left for the applicant
        return False
    return len(_chips(page, input_id)) == before - 1

def _entered_chip(page: Any, input_id: str, before: list[str]) -> str | None:
    """The chip Enter committed by itself, when the search had a single result.

    Workday commits a lone result on Enter while still listing it, ticked; clicking that
    option then *un*-selects it. American Century (2026-09): every skill was added by the
    Enter and removed by the click, and the step ended with none.
    """
    after = _chips(page, input_id)
    if len(after) != len(before) + 1:
        return None
    remaining = list(before)
    for chip in after:
        if chip in remaining:
            remaining.remove(chip)
        else:
            return chip
    return after[-1]

def _search_prompt(page: Any, input_id: str, term: str) -> list[str]:
    """Type one search into a prompt and return its settled options (duplicates kept)."""
    box = page.locator(f"[id='{input_id}']").first
    box.fill("", timeout=3000)
    box.fill(term, timeout=3000)
    box.press("Enter")
    options = page.locator(workday_prompts._OPEN_PROMPT_OPTIONS)
    previous: list[str] | None = None
    texts: list[str] = []
    for _ in range(16):
        page.wait_for_timeout(250)
        texts = [str(text).strip() for text in options.all_inner_texts()]
        texts = [text for text in texts if text and not _NO_ITEMS.match(text)]
        # Results stream in; settled means two identical non-empty reads.
        if texts and texts == previous:
            break
        previous = texts
    return texts

def _click_option(page: Any, input_id: str, texts: list[str], option: str, before: int) -> bool:
    """Click ``option`` in the open results; verified by exactly one new chip.

    Not clicked when a chip has already appeared: the option is then ticked, and a
    click would un-select it (`_entered_chip`).
    """
    now = _chips(page, input_id)
    if len(now) != before:
        return len(now) == before + 1 and option in now
    clicks.safe_click(
        page.locator(workday_prompts._OPEN_PROMPT_OPTIONS).nth(texts.index(option)),
        purpose="select",
        timeout=3000,
    )
    for _ in range(8):
        page.wait_for_timeout(250)
        if len(_chips(page, input_id)) == before + 1:
            return True
    return False

def _commit_skill(page: Any, input_id: str, term: str, option: str) -> bool:
    """Search ``term`` again and commit ``option`` from its results."""
    before = _chips(page, input_id)
    texts = _search_prompt(page, input_id, term)
    entered = _entered_chip(page, input_id, before)
    if entered is not None:
        if entered == option:
            return True
        _drop_chip(page, input_id, entered)
        return False
    return option in texts and _click_option(page, input_id, texts, option, len(before))

def _drop_chip(page: Any, input_id: str, text: str) -> bool:
    """Remove the last chip reading ``text`` (one Enter committed without our choosing)."""
    chips = _chips(page, input_id)
    if text not in chips:
        return False
    return _remove_chip(page, input_id, len(chips) - 1 - chips[::-1].index(text))

def fill_skills(
    page: Any,
    skills: list[str],
    *,
    choose_many: Callable[[dict[str, list[str]]], dict[str, str | None]] | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
    deadline: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Enter the prepared skills into a Workday Skills prompt, one search per skill.

    Each skill is typed and an option naming it exactly (or by its abbreviation) is
    picked. The skills with no such option are then put to ``choose_many`` in ONE call,
    with the options each search actually showed; a pick outside those options is
    ignored. Chips already on the prompt are kept and not re-added. Returns the committed
    chips and the skills left for the applicant.
    """
    from resume_tailor.apply.forms.field_matcher import (  # noqa: PLC0415
        match_skill_option,
        same_skill_in,
    )

    try:
        prompts = [
            item
            for item in page.evaluate(workday_prompts.PROMPTS_JS) or []
            if isinstance(item, dict)
        ]
    except Exception:  # noqa: BLE001
        return [], []
    prompt = next((item for item in prompts if is_skills_prompt(item)), None)
    if prompt is None or not skills:
        return [], []
    input_id = str(prompt["input_id"])
    label = str(prompt.get("label") or "Skills")
    committed: list[dict[str, Any]] = []
    review: list[str] = []
    unmatched: dict[str, list[str]] = {}

    def out_of_time() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    def record(skill: str, option: str, how: str) -> None:
        progress(f"Workday: added skill {skill} -> {option} ({how})")
        committed.append({"key": "skills", "label": label, "value": option,
                          "selector": f"[id='{input_id}']"})

    def on_form(option: str) -> bool:
        # Two skills can resolve to one option ("HuggingFace", "Hugging Face"), and a
        # Continue run finds the first run's chips: Workday rejects the whole step with
        # "You cannot enter duplicate skills" (F5, 2026-09), so an option already
        # committed as a chip is never clicked again.
        return same_skill_in(_chips(page, input_id), option)

    remove_duplicate_chips(page, input_id, progress)
    progress(f"Workday: entering {len(skills)} skill(s) one at a time")
    for skill in dict.fromkeys(s.strip() for s in skills if s.strip()):
        if out_of_time():
            review.append(skill)
            continue
        chips = _chips(page, input_id)
        if match_skill_option(chips, skill):
            continue  # already on the form
        try:
            texts = _search_prompt(page, input_id, skill)
            entered = _entered_chip(page, input_id, chips)
            if entered is not None:
                # Enter committed the single result: keep it when it names the skill,
                # never click it (that would un-select it); otherwise take it back off
                # and let the model judge it like any other near miss.
                if match_skill_option([entered], skill) and not same_skill_in(chips, entered):
                    record(skill, entered, "exact")
                    continue
                _drop_chip(page, input_id, entered)
                if not same_skill_in(chips, entered):
                    unmatched[skill] = [entered]
                continue
            chosen = match_skill_option(texts, skill)
            if chosen and same_skill_in(chips, chosen):
                continue  # this option is already a chip, under another skill's name
            if chosen and _click_option(page, input_id, texts, chosen, len(chips)):
                record(skill, chosen, "exact")
            elif chosen:
                review.append(skill)
            elif texts:
                unmatched[skill] = list(dict.fromkeys(texts))[:25]
            else:
                review.append(skill)
        except Exception:  # noqa: BLE001 - one bad search does not stop the rest
            review.append(skill)

    if unmatched and choose_many is not None and not out_of_time():
        progress(f"Workday: asking the model about {len(unmatched)} skill(s) with no exact option")
        try:
            picks = choose_many(unmatched)
        except Exception as exc:  # noqa: BLE001
            progress(f"Workday: skill matching failed ({type(exc).__name__}); left for review")
            picks = {}
        used: set[str] = {str(c["value"]) for c in committed}
        for skill, options in unmatched.items():
            pick = picks.get(skill)
            if not pick or pick not in options or pick in used or out_of_time():
                review.append(skill)
                continue
            if on_form(pick):
                continue  # the model chose a skill the form already lists
            try:
                ok = _commit_skill(page, input_id, skill, pick)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                used.add(pick)
                record(skill, pick, "model")
            else:
                review.append(skill)
    else:
        review.extend(unmatched)
    with contextlib.suppress(Exception):
        page.locator(f"[id='{input_id}']").first.press("Escape")
    # Escape on the input can leave the results list (and its full-viewport dismiss
    # layer) open, which then swallows the next clicks: the Add buttons below it.
    workday_page.close_stray_popups(page)
    return committed, review
