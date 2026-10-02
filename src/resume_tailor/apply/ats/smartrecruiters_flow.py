"""SmartRecruiters' one-click form: City, Experience, Education, Resume and Message.

The form (``/oneclick-ui/``, captured live 2026-09-27 on Resultant and Wellmark) is an
Angular app built from ``spl-*`` web components whose controls sit in open shadow roots;
Playwright's CSS locators pierce them. Each area is found by its ``data-test`` attribute:

- City: ``div[data-test=personal-info-location] spl-autocomplete`` — a typeahead whose
  options (``spl-select-option``, text "Fountain Valley, CA, US") load from a location
  search; only a clicked option commits, as the host's ``value`` object (``city``,
  ``region``, ``stateCode``, ``country``). Typed text left uncommitted is cleared on blur.
  Some tenants (Wellmark) do not ask for a city at all.
- Experience / Education: ``div[data-test=experience|education]``, an "Add" button
  (``oc-button[data-test=add-experience]``) opening an inline editor
  (``[data-test=experience-edit-form]``) with typeaheads for title/company/institution
  (a ``#spl-custom-option`` commits the typed text), plain inputs for major/degree, a
  description textarea, flatpickr month pickers that accept typed "MM/YYYY" + Enter, and
  Save/Cancel. A saved entry renders as ``oc-experience-entry`` / ``oc-education-entry``.
- Resume: ``spl-dropzone[data-test=resume-upload]``; its ``input#file-input`` shares the id
  with the "Easy Apply" parse-and-prefill dropzone at the top of the form, which is never
  used. The accepted file shows as a file-list item carrying its name.
- Message: ``oc-textarea[data-test=hiring-manager-message-text] textarea`` under "Message
  to the Hiring Team".

The second step (``/screening``, captured live 2026-09-27 on Resultant) holds the
screening questions, each in a ``[data-test=question-container]``: Yes/No
``spl-radio-group``s whose ``spl-radio`` options have no native input, ``spl-autocomplete``
selects whose options load on ArrowDown, ``spl-input`` text boxes, and declaration
``spl-checkbox``es. The question text is slotted into the control's shadow ``<label>``
(``[slot=label-content]``), so the generic pass reads every label as "*". `fill_screening`
answers them through `questions` (profile facts and what follows from them), then
remembered answers (`answer_memory`); a declaration is never ticked for the applicant, and
a question with no known answer is left for review.

Like `workday_repeaters`: an entry already listed is reused, never edited or deleted; an
answer already present is kept; anything not verified on the page is reported for review.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from resume_tailor.apply.answers import answer_memory, questions
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.funnel.packet_models import Packet

from . import smartrecruiters_entries, smartrecruiters_location, smartrecruiters_page


def _resume_state(zone: Any) -> dict[str, Any]:
    try:
        state = zone.evaluate(smartrecruiters_page._DROPZONE_FILES_JS)
    except Exception:  # noqa: BLE001
        return {"names": [], "listed": 0}
    return state if isinstance(state, dict) else {"names": [], "listed": 0}


def fill_resume(page: Any, resume_path: str | None) -> tuple[list[dict[str, str]], list[str]]:
    """Set the resume on the Resume section's dropzone and see its name listed.

    The "Easy Apply" dropzone at the top of the form also takes a resume, but parses it
    to prefill the form; it is never used.
    """
    zone = page.locator(f"{smartrecruiters_page._RESUME} spl-dropzone").first
    if not smartrecruiters_page._present(
        page.locator(f"{smartrecruiters_page._RESUME} spl-dropzone")
    ):
        return [], []
    state = _resume_state(zone)
    if state.get("listed"):
        name = (state.get("names") or [""])[0] or "a file"
        return [{"label": "Resume", "value": name, "state": "preserved"}], []
    if not resume_path or not Path(resume_path).is_file():
        return [], ["Resume: no prepared resume file to attach"]
    name = Path(resume_path).name
    try:
        page.locator(f"{smartrecruiters_page._RESUME} input[type=file]").first.set_input_files(
            resume_path, timeout=5000
        )
    except Exception:  # noqa: BLE001
        return [], ["Resume: the file could not be set on the upload"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        state = _resume_state(zone)
        if name in state.get("names", []):
            return [{"label": "Resume", "value": name}], []
        page.wait_for_timeout(250)
    return [], [f"Resume: {name} was set but is not listed on the form"]


def fill_message(page: Any, cover_letter: str) -> tuple[list[dict[str, str]], list[str]]:
    """Put the cover letter in "Message to the Hiring Team" when the box is empty."""
    boxes = page.locator(smartrecruiters_page._MESSAGE)
    if not smartrecruiters_page._present(boxes) or not cover_letter.strip():
        return [], []
    box = boxes.first
    try:
        current = box.input_value()
    except Exception:  # noqa: BLE001
        return [], ["Message to the Hiring Team"]
    if current.strip():
        kept = {"label": "Message to the Hiring Team", "value": current[:60], "state": "preserved"}
        return [kept], []
    review: list[str] = []
    if smartrecruiters_entries._set_text(
        box, cover_letter.strip(), label="Message to the Hiring Team", review=review
    ):
        with contextlib.suppress(Exception):
            box.evaluate("e => e.blur()")
        return [{"label": "Message to the Hiring Team", "value": "cover letter"}], review
    return [], [*review, "Message to the Hiring Team"]


#: Every screening question on the page, one record per control: ``kind`` (radio, select,
#: text, checkbox), the control's ``id``, the ``question``, whether it is ``required``,
#: the ``value`` already given ("" when none) and, for radios, the ``options``. The
#: containers sit inside open shadow roots, so they are searched for deeply.
_QUESTIONS_JS = r"""() => {
  const deep = (root, sel, out = []) => {
    out.push(...root.querySelectorAll(sel));
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) deep(el.shadowRoot, sel, out);
    return out;
  };
  const text = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const labelOf = (host) => {
    const slotted = host.querySelector(':scope > [slot=label-content]');
    if (slotted) return text(slotted.textContent);
    return text(host.getAttribute('aria-label')).replace(/^Select\s+/i, '');
  };
  const HOSTS = 'spl-radio-group, spl-autocomplete, spl-input, spl-textarea, spl-checkbox';
  // Up one level through shadow boundaries; a control inside another (the text box
  // inside a select, the info checkbox inside its question field) belongs to that one.
  const up = (n) => n.parentElement || (n.getRootNode() && n.getRootNode().host) || null;
  const nested = (el, box) => {
    for (let n = up(el); n && n !== box; n = up(n)) if (n.matches && n.matches(HOSTS)) return true;
    return false;
  };
  const out = [];
  for (const box of deep(document, '[data-test=question-container]')) {
    for (const host of deep(box, HOSTS)) {
      if (!host.id || nested(host, box)) continue;
      const required = host.hasAttribute('required');
      const question = labelOf(host);
      if (host.localName === 'spl-radio-group') {
        const options = [...host.querySelectorAll('spl-radio')].map((r) => ({
          label: text(r.getAttribute('label')), value: r.getAttribute('value') || '',
          checked: r.getAttribute('aria-checked') === 'true',
        }));
        const picked = options.find((o) => o.checked);
        out.push({kind: 'radio', id: host.id, question, required, options,
                  value: picked ? picked.label : ''});
      } else if (host.localName === 'spl-autocomplete') {
        const v = host.value;
        const shown = v && typeof v === 'object'
          ? text(v.label || v.text || v.name || v.value || JSON.stringify(v)) : text(v);
        out.push({kind: 'select', id: host.id, question, required, value: shown});
      } else if (host.localName === 'spl-checkbox') {
        const input = host.shadowRoot && host.shadowRoot.querySelector('input[type=checkbox]');
        out.push({kind: 'checkbox', id: host.id, required,
                  question: question || text(host.textContent),
                  value: input && input.checked ? 'checked' : ''});
      } else {
        const field = host.shadowRoot && host.shadowRoot.querySelector('input, textarea');
        out.push({kind: 'text', id: host.id, question, required,
                  value: text(field ? field.value : host.value)});
      }
    }
  }
  // The privacy-notice consent below the questions: the applicant's to give.
  for (const consent of deep(document, 'spl-checkbox[data-test=consent-box]')) {
    const input = consent.shadowRoot && consent.shadowRoot.querySelector('input[type=checkbox]');
    out.push({kind: 'checkbox', id: consent.id, question: 'Consent to the privacy notice',
              required: consent.hasAttribute('required'),
              value: input && input.checked ? 'checked' : ''});
  }
  return out;
}"""

def _choose_radio(page: Any, group_id: str, label: str) -> bool:
    literal = label.replace("\\", "\\\\").replace('"', '\\"')
    radio = page.locator(f'spl-radio-group[id="{group_id}"] spl-radio[label="{literal}"]').first
    try:
        smartrecruiters_location._activate(radio)
        page.wait_for_timeout(200)
        return radio.get_attribute("aria-checked") == "true"
    except Exception:  # noqa: BLE001
        return False


def _choose_select(
    host: Any, question: questions.Question, key: str, answers: list[str],
) -> str | None:
    """Open the select and click the option that says one of ``answers``; the text committed.

    ArrowDown lists the options; a long list (majors, schools) shows only its first ones,
    so when none of them says the answer, the answer's search terms are typed to filter it.
    """
    field = host.locator("input[role=combobox]").first
    try:
        field.focus(timeout=3000)
        field.press("ArrowDown", timeout=3000)
    except Exception:  # noqa: BLE001
        return None

    def pick(options: list[tuple[str, str]]) -> tuple[str, str] | None:
        real = [
            item
            for item in options
            if item[0]
            not in {smartrecruiters_page._CUSTOM_OPTION, smartrecruiters_page._MANUAL_LOCATION}
        ]
        offered = replace(question, options=tuple(text for _value, text in real))
        chosen = questions.choose(offered, key, answers)
        value = next((v for v, t in real if t == chosen), None) if chosen else None
        return (value, chosen) if value is not None and chosen else None

    hit = pick(smartrecruiters_location._options(host, want_results=True))
    if hit is None:
        for term in field_matcher.search_terms(key, answers[0]) if answers else []:
            found: list[tuple[str, str]] = []

            def choose(options: list[tuple[str, str]], found: list = found) -> str | None:
                picked = pick(options)
                if picked:
                    found.append(picked)
                return picked[0] if picked else None

            if smartrecruiters_location._type_and_pick(host, term, choose, want_results=True):
                return (
                    found[0][1]
                    if smartrecruiters_location._committed(host) not in (None, "", [], {})
                    else None
                )
        smartrecruiters_location._clear_typeahead(host)
        return None
    literal = hit[0].replace("\\", "\\\\").replace('"', '\\"')
    try:
        smartrecruiters_location._activate(
            host.locator(f'spl-select-option[value="{literal}"]').first
        )
        host.page.wait_for_timeout(300)
    except Exception:  # noqa: BLE001
        smartrecruiters_location._clear_typeahead(host)
        return None
    return hit[1] if smartrecruiters_location._committed(host) not in (None, "", [], {}) else None


def _short(question: str) -> str:
    return question if len(question) <= 90 else question[:87].rstrip() + "..."


def fill_screening(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Answer the screening step's questions from profile facts and remembered answers.

    What each question asks and its answer come from `questions` (the decision layer every
    fill path shares). Declarations and acknowledgements are never ticked for the
    applicant; a question no profile fact or saved answer covers is left for review, never
    guessed.
    """
    try:
        found = page.evaluate(_QUESTIONS_JS) or []
    except Exception:  # noqa: BLE001
        return [], []
    facts = questions.facts_from_packet(packet)
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for item in found:
        text = str(item.get("question") or item.get("id") or "question")
        label = _short(text)
        selector = f'[id="{item.get("id")}"]'
        if item.get("value"):
            filled.append({"label": label, "value": str(item["value"]), "state": "preserved"})
            continue
        kind = item.get("kind")
        if kind == "checkbox":
            if item.get("required"):
                review.append(f"{label}: read and tick it yourself")
            continue
        options = tuple(str(opt.get("label") or "") for opt in item.get("options") or [])
        question = questions.Question(
            text, kind={"radio": "choice", "select": "typeahead"}.get(str(kind), "text"),
            options=options,
        )
        match = questions.classify(question)
        key = match.key if match else ""
        answers = questions.answers(match, question, facts)
        if not answers and key not in field_matcher.EEO_KEYS:
            recalled = answer_memory.recall(
                text, company=packet.company, ats="smartrecruiters", canonical_key=key
            )
            if recalled is not None and not recalled.needs_review:
                answers = [recalled.answer]
        if not answers:
            if item.get("required") or key:
                review.append(f"{label}: no answer in the applicant profile")
            continue
        answer: str | None = None
        if kind == "radio":
            chosen = questions.choose(question, key, answers)
            if chosen is None:
                review.append(f"{label}: no option matches {answers[0]!r}")
                continue
            if _choose_radio(page, str(item["id"]), chosen):
                answer = chosen
        elif kind == "select":
            host = page.locator(f"spl-autocomplete{selector}").first
            answer = _choose_select(host, question, key, answers)
        elif kind == "text":
            control = page.locator(f"{selector} input, {selector} textarea").first
            if smartrecruiters_entries._set_text(control, answers[0], label=label, review=review):
                answer = answers[0]
                with contextlib.suppress(Exception):
                    control.evaluate("e => e.blur()")
        if answer is None:
            review.append(f"{label}: could not set {answers[0]!r}")
            continue
        progress(f"SmartRecruiters: answered {label[:60]} = {answer}")
        filled.append({"label": label, "value": answer})
    return filled, review


def screening_selectors(page: Any) -> set[str]:
    """Selectors the generic pass reports for the screening controls this flow owns."""
    try:
        questions = page.evaluate(_QUESTIONS_JS) or []
    except Exception:  # noqa: BLE001
        return set()
    return {f"#{item['id']}" for item in questions if item.get("id")}


def fill(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None],
    *,
    resume_path: str | None = None,
    deadline: float | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Fill every area this form step shows; ``(filled, needs_review)`` like Workday's.

    ``filled`` records are ``{"label", "value"}`` (plus ``"state"`` "preserved" for an
    answer that was already there, "partial" for a saved entry with a field left for
    review); ``needs_review`` holds human labels. Past ``deadline`` (``time.monotonic``)
    no further entry is added; the rest are listed for review.
    """
    filled: list[dict[str, str]] = []
    review: list[str] = []
    for step in (
        lambda: smartrecruiters_location.fill_city(page, packet.fields),
        lambda: fill_resume(page, resume_path),
        lambda: fill_message(page, packet.cover_letter),
        lambda: smartrecruiters_entries.fill_experience(page, packet, progress, deadline=deadline),
        lambda: smartrecruiters_entries.fill_education(page, packet, progress, deadline=deadline),
        lambda: fill_screening(page, packet, progress),
    ):
        done, left = step()
        filled.extend(done)
        review.extend(label for label in left if label not in review)
    return filled, review
