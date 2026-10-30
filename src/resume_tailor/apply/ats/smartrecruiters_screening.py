"""SmartRecruiters' second step (``/screening``): the screening questions.

Captured live 2026-09-27 on Resultant. Each question sits in a
``[data-test=question-container]``: Yes/No ``spl-radio-group``s whose ``spl-radio``
options have no native input, ``spl-autocomplete`` selects whose options load on
ArrowDown, ``spl-input`` text boxes, and declaration ``spl-checkbox``es; the privacy-notice
consent (``spl-checkbox[data-test=consent-box]``) sits below them. The question text is
slotted into the control's shadow ``<label>`` (``[slot=label-content]``), so the generic
pass reads every label as "*". `fill_screening` answers them through `questions` (profile
facts and what follows from them), then remembered answers (`answer_memory`); a notice is
ticked only when the applicant's standing choice accepts it, and a question with no known
answer is left for review. An answer can reveal a follow-up question (Intuitive's export
question opens a citizenship list, 2026-10-30), answered on a further pass.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from resume_tailor.apply.answers import answer_memory, form_facts, questions
from resume_tailor.apply.forms import field_matcher
from resume_tailor.apply.funnel.packet_models import Packet

from . import smartrecruiters_entries, smartrecruiters_location, smartrecruiters_page

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
  // A follow-up question's container sits inside the one that reveals it (Intuitive's
  // citizenship list under its export question, 2026-10-30): each control is read once,
  // and only while it shows.
  const seen = new Set();
  for (const box of deep(document, '[data-test=question-container]')) {
    for (const host of deep(box, HOSTS)) {
      if (!host.id || nested(host, box) || seen.has(host)) continue;
      seen.add(host);
      if (!host.getClientRects().length) continue;
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
  // The privacy-notice consent below the questions, with its own wording ("You declare
  // that you have read and agree to the privacy notice of Intuitive.").
  for (const consent of deep(document, 'spl-checkbox[data-test=consent-box]')) {
    const input = consent.shadowRoot && consent.shadowRoot.querySelector('input[type=checkbox]');
    out.push({kind: 'checkbox', id: consent.id, consent: true,
              question: labelOf(consent) || text(consent.textContent)
                || 'Consent to the privacy notice',
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


#: Passes over the screening step: an answer can reveal a follow-up question (Intuitive's
#: export question opens a citizenship list), which the next pass answers.
_SCREENING_PASSES = 3


def fill_screening(
    page: Any,
    packet: Packet,
    progress: Callable[[str], None] = lambda _msg: None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Answer the screening step's questions from profile facts and remembered answers.

    What each question asks and its answer come from `questions` (the decision layer every
    fill path shares). A required notice is ticked only when it is a routine one the
    applicant's standing choice accepts (`form_facts.Consent`: plain notices such as a
    privacy notice; binding declarations only with agreements switched on); a question no
    profile fact or saved answer covers is left for review, never guessed. Questions an
    answer reveals are answered on a further pass, up to `_SCREENING_PASSES`.
    """
    facts = questions.facts_from_packet(packet)
    filled: list[dict[str, str]] = []
    review: list[str] = []
    seen: set[tuple[str, str]] = set()
    for attempt in range(_SCREENING_PASSES):
        if attempt:
            page.wait_for_timeout(300)  # what the last answers reveal draws a moment later
        try:
            found = page.evaluate(_QUESTIONS_JS) or []
        except Exception:  # noqa: BLE001
            break
        # By wording, not id: the page may number its controls afresh when it re-renders.
        fresh = [item for item in found
                 if (str(item.get("kind")), str(item.get("question"))) not in seen]
        if not fresh:
            break
        seen.update((str(item.get("kind")), str(item.get("question"))) for item in fresh)
        done, left = _answer_screening(page, packet, facts, fresh, progress)
        filled.extend(done)
        review.extend(left)
    return filled, review


def _tick_notice(page: Any, host_id: str) -> bool:
    """Press a notice's checkbox (the native box takes the press) and see it checked."""
    literal = host_id.replace("\\", "\\\\").replace('"', '\\"')
    box = page.locator(f'spl-checkbox[id="{literal}"] input[type=checkbox]').first
    try:
        if not box.is_checked():
            smartrecruiters_location._activate(box)
            page.wait_for_timeout(200)
        return box.is_checked()
    except Exception:  # noqa: BLE001
        return False


def _answer_screening(
    page: Any,
    packet: Packet,
    facts: questions.Facts,
    found: list[dict[str, Any]],
    progress: Callable[[str], None],
) -> tuple[list[dict[str, str]], list[str]]:
    """One pass of `fill_screening` over the questions ``found`` on the page."""
    consent = form_facts.Consent.from_fields(packet.fields)
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
            if not item.get("required"):
                continue
            if (form_facts.acknowledgement(text) == "routine" and consent.accepts(text)
                    and _tick_notice(page, str(item.get("id") or ""))):
                progress(f"SmartRecruiters: answered {label[:60]} = checked")
                filled.append({"label": label, "value": "checked"})
            else:
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
        progress(f"SmartRecruiters: answered {label[:60]} = {answer_memory.shown(label, answer)}")
        filled.append({"label": label, "value": answer})
    return filled, review


def screening_selectors(page: Any) -> set[str]:
    """Selectors the generic pass reports for the screening controls this flow owns."""
    try:
        questions = page.evaluate(_QUESTIONS_JS) or []
    except Exception:  # noqa: BLE001
        return set()
    return {f"#{item['id']}" for item in questions if item.get("id")}
