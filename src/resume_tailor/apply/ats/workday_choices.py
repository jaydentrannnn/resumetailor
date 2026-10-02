"""Workday radio groups, choice checkboxes and the voluntary self-identify step."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from resume_tailor.apply.answers import questions
from resume_tailor.apply.driver import clicks
from resume_tailor.apply.forms import field_matcher

from . import workday_dropdowns, workday_page

# -- Yes/No radio questions -------------------------------------------------------------

#: Unanswered radio groups inside Workday form fields, with their legend question.
RADIOS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const out = [];
  for (const field of document.querySelectorAll("[data-automation-id^='formField-']")) {
    const radios = [...field.querySelectorAll("input[type='radio']")].filter(vis);
    if (!radios.length || radios.some(r => r.checked)) continue;
    const legend = field.querySelector('legend');
    out.push({
      field: field.getAttribute('data-automation-id'),
      question: (legend ? legend.innerText : '').replace(/\*\s*$/, '').trim(),
      options: radios.map(r => {
        const l = r.id && document.querySelector(`label[for="${CSS.escape(r.id)}"]`);
        return {id: r.id, label: l ? (l.innerText || '').trim() : (r.value || '')};
      }).filter(o => o.id),
    });
  }
  return out;
}"""

def _norm_company(value: str) -> str:
    # "Deloitte & Touche LLP" and "Deloitte and Touche" are one firm.
    value = re.sub(r"[^a-z0-9 ]+", " ", value.casefold().replace("&", " and "))
    value = re.sub(r"\b(inc|llc|llp|lp|plc|ltd|corp|corporation|company|co|group)\b", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def previously_employed(company: str, employers: Iterable[str]) -> bool:
    """True only when the posting company is one of the applicant's own employers."""
    target = _norm_company(company)
    if not target:
        return False
    return any(
        (name := _norm_company(employer)) and (name == target or re.search(rf"\b{re.escape(target)}\b", name))
        for employer in employers
    )

def fill_radios(
    page: Any,
    fields: dict[str, str],
    *,
    company: str,
    employers: Iterable[str],
    role: str = "",
    experience_titles: Iterable[str] = (),
    progress: Callable[[str], None] = lambda _msg: None,
    blank: list[dict[str, str]] | None = None,
    review: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Answer unanswered Yes/No radio questions from profile facts, and only those.

    A self-identification question no option answers is reported in ``review`` with the
    options it offered (`choice_failure`).

    What a question asks, its answer and the option that says it come from `questions`:
    "Have you ever been employed by <company>?" from the applicant's own experience
    entries, "Are you currently enrolled?" from the graduation date, every other question
    from a profile fact whose value names one option (exactly, or a self-identification
    answer's long form). Anything else stays for the resolver or the applicant.
    """
    try:
        groups = page.evaluate(RADIOS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    facts = questions.facts_for(
        fields, company=company, role=role, employers=employers,
        experience_titles=experience_titles,
    )
    committed: list[dict[str, Any]] = []
    for group in groups:
        question = str(group.get("question") or "")
        options = group.get("options") or []
        labels = [str(opt.get("label", "")) for opt in options]
        asked = questions.Question(question, kind="choice", options=tuple(labels))
        match = (
            questions.Match("previous_worker", question.casefold())
            if group.get("field") == "formField-candidateIsPreviousWorker"
            else questions.classify(asked)
        )
        key = match.key if match else ""
        if not key or key in workday_dropdowns._BLANK_EXEMPT:
            continue
        answers = questions.answers(match, asked, facts)
        if not answers:
            workday_dropdowns._note_blank(blank, questions.profile_field(key), question, True)
            continue
        value = answers[0]
        chosen = questions.choose(asked, key, answers)
        matches = [opt for opt in options if str(opt.get("label", "")) == chosen] if chosen else []
        if len(matches) != 1:
            if key in field_matcher.EEO_KEYS and not any(opt.get("checked") for opt in options):
                line = workday_dropdowns.choice_failure(question or key, value, labels)
                progress(f"Workday: {line}")
                if review is not None:
                    review.append(line)
            continue
        try:
            clicks.safe_click(page.locator(f"label[for='{matches[0]['id']}']").first, purpose="select", timeout=3000)
            checked = page.locator(f"[id='{matches[0]['id']}']").first.is_checked()
        except Exception:  # noqa: BLE001
            checked = False
        if checked:
            progress(f"Workday: answered {question[:60]} = {matches[0]['label']}")
            committed.append({"key": key, "label": question, "value": matches[0]["label"],
                              "selector": f"[id='{matches[0]['id']}']"})
    return committed

# -- Self-identification: checkbox answers, Self Identify step ---------------------------

#: Groups of visible checkboxes inside one Workday form field (or fieldset), with the
#: question and each option's label: the disability form ("Yes, I have a disability" /
#: "No, I do not have a disability" / "I do not want to answer") and tenants that render
#: race or veteran status as checkboxes.
CHECKBOX_GROUPS_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const root = document.querySelector("[data-automation-id='applyFlowPage']") || document;
  const groups = new Map();
  for (const box of root.querySelectorAll("input[type='checkbox']")) {
    const label = box.id && document.querySelector(`label[for="${CSS.escape(box.id)}"]`);
    if (!box.id || !(vis(box) || vis(label))) continue;
    const container = box.closest("[data-automation-id^='formField-'], fieldset, [role='group']") || box.parentElement;
    if (!groups.has(container)) groups.set(container, []);
    groups.get(container).push({id: box.id, label: label ? (label.innerText || '').trim() : '', checked: box.checked});
  }
  return [...groups].filter(([, options]) => options.length > 1).map(([container, options]) => {
    // American Century's "-CheckboxGroup" fieldset holds only the boxes; its question is
    // the legend of the enclosing form field (2026-09).
    const field = container.closest("[data-automation-id^='formField-']");
    const legend = container.querySelector("legend, label:not([for])")
      || (field && field.querySelector("legend, label:not([for])"));
    return {question: (legend ? legend.innerText : '').replace(/\*\s*$/, '').trim(), options};
  });
}"""

#: Text and split-date controls of the Self Identify step, by their field label.
SELF_ID_JS = r"""() => {
  const vis = e => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const root = document.querySelector("[data-automation-id='applyFlowPage']") || document;
  const out = [];
  for (const field of root.querySelectorAll("[data-automation-id^='formField-']")) {
    const label = field.querySelector('label, legend');
    const text = (label ? label.innerText : '').replace(/\*\s*$/, '').trim();
    const month = field.querySelector("input[id$='-dateSectionMonth-input']");
    if (month) {
      const control = month.id.slice(0, -'-dateSectionMonth-input'.length);
      out.push({kind: 'date', label: text, control,
                day: !!field.querySelector("input[id$='-dateSectionDay-input']")});
      continue;
    }
    const input = [...field.querySelectorAll("input[type='text'], input:not([type])")].filter(vis)[0];
    if (input && input.id && !input.closest("[data-automation-id='multiselectInputContainer']")) {
      out.push({kind: 'text', label: text, id: input.id, value: (input.value || '').trim()});
    }
  }
  return out;
}"""

#: The disability form's answers are its own options; its question rarely says so.
_DISABILITY_OPTION = re.compile(r"\bdisabilit", re.I)

_SELF_ID_STEP = re.compile(r"self[\s-]*identif", re.I)

_NAME_LABEL = re.compile(r"^(?:your |full |legal )*name$|^signature$", re.I)

_EMPLOYEE_ID = re.compile(r"employee\s*(?:id|number)", re.I)

_DATE_LABEL = re.compile(r"^(?:today'?s )?date(?: signed)?$", re.I)

def _group_key(group: dict[str, Any]) -> str | None:
    labels = [str(option.get("label") or "") for option in group.get("options") or []]
    if sum(bool(_DISABILITY_OPTION.search(label)) for label in labels) >= 2:
        return "disability_status"
    key = workday_dropdowns.key_for_label(str(group.get("question") or ""))
    return key if key in field_matcher.EEO_KEYS or key == "previous_worker" else None

#: The "none of these" option of a checkbox group ("No", "None of the above").
_NONE_OPTION = re.compile(r"^(?:no|none(?: of the above| of these)?|not applicable|n/?a)\.?$", re.I)

def _previous_employer_options(labels: list[str], employers: Iterable[str]) -> list[str]:
    """"Have you worked for any of the listed firms?" as checkboxes (American Century,
    2026-09): the listed firms the applicant worked for, else the one "No" option."""
    names = [_norm_company(name) for name in employers if _norm_company(name)]
    worked = [label for label in labels if (firm := _norm_company(label)) and any(
        firm == name or re.search(rf"\b{re.escape(firm)}\b", name) for name in names
    )]
    if worked:
        return worked
    none = [label for label in labels if _NONE_OPTION.match(label.strip())]
    return none if len(none) == 1 else []

def _tick(page: Any, box_id: str) -> bool:
    box = page.locator(f"[id='{box_id}']").first
    if not box.is_checked():
        try:
            clicks.safe_click(page.locator(f"label[for='{box_id}']").first, purpose="select", timeout=3000)
        except Exception:  # noqa: BLE001 - an unlabelled box takes the click itself
            box.check(timeout=2000)
    return bool(box.is_checked())

def fill_choice_checkboxes(
    page: Any,
    fields: dict[str, str],
    *,
    progress: Callable[[str], None] = lambda _msg: None,
    review: list[str] | None = None,
    employers: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Tick the one option of each self-identification checkbox group that means the
    profile's answer (`field_matcher.eeo_pattern`: "No" -> "No, I do not have a
    disability..."). A group with a ticked box is the applicant's answer and is kept; no
    unique option is left for review, never guessed.

    A "worked for any of the listed firms?" group is answered from ``employers``
    (`_previous_employer_options`), not left to the model: the same question then gets
    the same answer on every posting.
    """
    employers = list(employers)
    try:
        groups = page.evaluate(CHECKBOX_GROUPS_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    for group in groups:
        key = _group_key(group)
        options = group.get("options") or []
        if not key or any(option.get("checked") for option in options):
            continue
        question = str(group.get("question") or "") or key.replace("_", " ").capitalize()
        labels = [str(option.get("label") or "") for option in options]
        if key == "previous_worker":
            picks = _previous_employer_options(labels, employers)
        else:
            chosen = None
            for candidate in field_matcher.choice_values(key, fields):
                chosen = field_matcher.closest_option(labels, candidate, key=key)
                if chosen:
                    break
            picks = [chosen] if chosen else []
        if not picks:
            if key != "previous_worker" and fields.get(key) and review is not None:
                review.append(workday_dropdowns.choice_failure(question, fields[key], labels))
            continue
        for chosen in picks:
            box_id = next(str(option["id"]) for option in options if option.get("label") == chosen)
            try:
                ticked = _tick(page, box_id)
            except Exception:  # noqa: BLE001
                ticked = False
            if ticked:
                progress(f"Workday: ticked {chosen[:70]}")
                committed.append({"key": key, "label": question, "value": chosen, "selector": f"[id='{box_id}']"})
            elif review is not None:
                review.append(f"{question}: could not tick {chosen}")
    return committed

def fill_self_identify(
    page: Any,
    fields: dict[str, str],
    *,
    today: date,
    progress: Callable[[str], None] = lambda _msg: None,
    review: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The Self Identify step's signature: Name (the applicant's full name) and today's
    Date; Employee ID stays blank (applicants are not employees). Existing answers are
    kept. The disability answer is `fill_choice_checkboxes`'s.
    """
    from resume_tailor.apply.ats import workday_repeaters  # noqa: PLC0415

    try:
        controls = page.evaluate(SELF_ID_JS) or []
    except Exception:  # noqa: BLE001
        return []
    committed: list[dict[str, Any]] = []
    name = fields.get("full_name", "")
    for control in controls:
        label = str(control.get("label") or "")
        if control.get("kind") == "text" and _EMPLOYEE_ID.search(label):
            progress("Workday: leaving Employee ID blank")
        elif control.get("kind") == "text" and _NAME_LABEL.match(label) and name:
            if control.get("value"):
                continue
            box = page.locator(f"[id='{control['id']}']").first
            try:
                box.fill(name, timeout=3000)
                ok = str(box.input_value() or "").strip() == name
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                progress(f"Workday: signed {label} = {name}")
                committed.append({"key": "full_name", "label": label, "value": name,
                                  "selector": f"[id='{control['id']}']"})
            elif review is not None:
                review.append(label)
        elif control.get("kind") == "date" and _DATE_LABEL.match(label):
            parts = [("dateSectionMonth", f"{today.month:02d}")]
            if control.get("day"):
                parts.append(("dateSectionDay", f"{today.day:02d}"))
            parts.append(("dateSectionYear", str(today.year)))
            try:
                ok = workday_repeaters.fill_date_sections(page, str(control["control"]), parts)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                progress(f"Workday: dated {label} {today.isoformat()}")
                committed.append({"key": "signature_date", "label": label, "value": today.isoformat(),
                                  "selector": f"[id='{control['control']}-dateSectionMonth-input']"})
            elif review is not None:
                review.append(label)
    return committed

def is_self_identify_step(snap: dict[str, Any]) -> bool:
    """Workday's disability self-identification (CC-305) step."""
    return bool(_SELF_ID_STEP.search(workday_page.active_step(snap)))
