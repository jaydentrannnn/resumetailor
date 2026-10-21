"""Inspecting a form step in the page for the fields still blocking it (deterministic, no LLM)."""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


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
      const lbl = rootOf(el).querySelector(`label[for="${CSS.escape(el.id)}"]`);
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

  const helpFor = (el) => (el.getAttribute('aria-describedby') || '').split(/\\s+/)
    .map(id => document.getElementById(id)?.textContent || '').join(' ').trim();

  // The shared helpers (rootOf, deepQueryAll, honeypot, twinOwner) use these two.
  const labelFor = getLabel;
  /*DOM_COMMON*/

  // Separate components can reuse an id inside their own shadow roots (two "#phone"s):
  // such a selector is scoped by its hosts ("#host >> #phone", as Playwright chains it)
  // and kept only when the chain finds this element alone; else '' (not actionable).
  const inside = (node, part) => [
    ...deepQueryAll(node, part), ...(node.shadowRoot ? deepQueryAll(node.shadowRoot, part) : []),
  ];
  const resolveChain = (parts) => parts.reduce(
    (nodes, part) => [...new Set(nodes.flatMap(node => inside(node, part)))], [document]);
  const actionableSelector = (el) => {
    const sel = uniqueSelector(el);
    if (!sel || deepQueryAll(document, sel).length <= 1) return sel;
    const parts = [sel];
    for (let root = el.getRootNode(); root instanceof ShadowRoot; root = root.host.getRootNode()) {
      const hostSel = uniqueSelector(root.host);
      if (!hostSel) return '';
      parts.unshift(hostSel);
    }
    const found = resolveChain(parts);
    return found.length === 1 && found[0] === el ? parts.join(' >> ') : '';
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

  // A radio/checkbox group's question when no fieldset or form field names it (Lever puts
  // it in a div above a list of <label><input> options): the text of the nearest container
  // holding only this group, less the options' own words.
  const groupTitle = (group) => {
    const words = group.map(g => (g.closest('label')?.innerText || g.value || '').trim())
      .filter(Boolean);
    let node = group[0].parentElement;
    for (let depth = 0; node && depth < 8; depth++, node = node.parentElement) {
      if (!group.every(g => node.contains(g))) continue;
      const controls = node.querySelectorAll('input:not([type="hidden"]), select, textarea');
      if (Array.from(controls).some(c => !group.includes(c))) return '';
      let own = (node.innerText || '').replace(/[\\u2060\\u200b]/g, '');
      words.forEach(word => { own = own.split(word).join(' '); });
      own = own.replace(/[✱*]/g, ' ').replace(/\\s+/g, ' ').trim();
      if (own) return own;
    }
    return '';
  };

  const unresolved = [];
  const seenFields = new Set();

  // 1. Custom comboboxes / dropdown buttons (real popup triggers only)
  // React Select inputs do not always carry role=combobox (Epic Games' form).
  const dropdowns =
    '[role="combobox"], [aria-haspopup="listbox"], input[id^="react-select-"][id$="-input"]';
  deepQueryAll(document, dropdowns).forEach(el => {
    if (isVisible(el) && !notADropdown(el) && !honeypot(el)) {
      // One question per Workday form field, however many triggers it renders.
      const key = fieldKey(el);
      if (key && seenFields.has(key)) return;
      let current = el.innerText.trim();
      if (!current && el.value) current = el.value.trim();
      const singleVal = el.closest('.select__control, [class*="-control"]')?.querySelector('.select__single-value, [class*="-singleValue"]');
      if (singleVal) current = singleVal.innerText.trim();

      const label = getLabel(el);
      const sel = actionableSelector(el);
      const phoneCode = !!el.closest('.phone-input__country, [data-automation-id="formField-countryPhoneCode"]')
        || /dial(?:ing|ling)? code|calling code|phone country|country code/i.test(label);
      if (sel && (phoneCode || !current || current.toLowerCase().includes('select') || current.toLowerCase().includes('choose'))) {
        if (key) seenFields.add(key);
        unresolved.push({
          type: 'combobox',
          selector: sel,
          label: label || 'Dropdown selection',
          help: helpFor(el),
          current: current,
          invalid: invalid(el)
          ,phone_code_menu: phoneCode
        });
      }
    }
  });

  // 2. Unchecked required radio button groups
  const radioNames = new Set();
  deepQueryAll(document, 'input[type="radio"]').forEach(r => {
    if (r.name && !radioNames.has(r.name) && isVisible(r) && !honeypot(r)) {
      radioNames.add(r.name);
      const group = Array.from(
        rootOf(r).querySelectorAll(`input[type="radio"][name="${CSS.escape(r.name)}"]`));
      const anyChecked = group.some(g => g.checked);
      if (!anyChecked) {
        const question = r.closest(
          '[data-automation-id^="formField-"], fieldset, [role="radiogroup"]');
        const title = question?.querySelector('legend, label:not([for])');
        const label = title?.textContent?.trim() || groupTitle(group) || getLabel(r) || r.name;
        const options = group.map(g => getLabel(g) || g.value);
        unresolved.push({
          type: 'radiogroup',
          selector: `input[type="radio"][name="${r.name}"]`,
          label: label,
          help: helpFor(r),
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
  // Elsewhere: required checkboxes sharing one name (Lever's "check all that apply").
  const boxNames = new Set();
  deepQueryAll(document, 'input[type="checkbox"][name]').forEach(b => {
    if (boxNames.has(b.name) || b.closest('fieldset[data-automation-id$="-CheckboxGroup"]')) return;
    boxNames.add(b.name);
    const boxes = Array.from(
      rootOf(b).querySelectorAll(`input[type="checkbox"][name="${CSS.escape(b.name)}"]`));
    if (boxes.length < 2 || boxes.some(x => x.checked) || !boxes.some(isVisible)) return;
    if (!boxes.some(x => x.required || x.getAttribute('aria-required') === 'true')) return;
    unresolved.push({
      type: 'checkboxgroup',
      selector: `input[type="checkbox"][name="${b.name.replace(/"/g, '\\\\\\"')}"]`,
      label: groupTitle(boxes) || 'Checkbox group',
      options: boxes.map(x => (x.closest('label')?.innerText || getLabel(x) || x.value).trim()),
      invalid: boxes.some(invalid)
    });
  });

  // 2c. Filled boxes the form refuses (aria-invalid, or native validity for any reason
  // but emptiness): a typed answer in a shape the form does not take. Kept apart from
  // `unresolved`, since the value is the applicant's and never goes to the model.
  const rejected = [];
  const skipTypes = ['hidden', 'file', 'submit', 'button', 'image', 'reset', 'checkbox', 'radio'];
  deepQueryAll(document, 'input, textarea, select').forEach(el => {
    const type = (el.getAttribute('type') || el.tagName.toLowerCase()).toLowerCase();
    if (skipTypes.includes(type) || el.matches(TRIGGERS) || !isVisible(el)) return;
    if (honeypot(el) || twinOwner(el) || reactSelectBox(el)) return;
    if (!String(el.value || '').trim()) return;
    const refused = el.getAttribute('aria-invalid') === 'true'
      || (el.validity && !el.validity.valid && !el.validity.valueMissing);
    if (!refused) return;
    const sel = actionableSelector(el);
    const field = el.closest('[data-automation-id^="formField-"], .form-group, fieldset, label')
      || el.parentElement;
    const notices = field?.querySelectorAll(
      '[role="alert"], [class*="error" i], [data-automation-id*="error" i]') || [];
    const shown = Array.from(notices).map(node => (node.innerText || '').trim())
      .find(text => text && text.length < 200);
    rejected.push({
      selector: sel,
      ambiguous: !sel,  // a reused id no chain tells apart: noted, never retyped
      label: getLabel(el) || 'Field',
      help: helpFor(el),
      kind: el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : type,
      placeholder: el.getAttribute('placeholder') || '',
      message: shown || el.validationMessage || '',
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
    rejected: rejected.slice(0, 30),
    advance_disabled: advanceDisabled
  };
}
"""

def extract_page_blockers(page: Any) -> dict[str, Any]:
    """Inspect the page (open shadow roots included) for validation errors, unresolved
    custom controls, and filled boxes the form ``rejected``."""
    from resume_tailor.apply.forms import fill_page  # noqa: PLC0415 - forms imports answers

    try:
        data = page.evaluate(fill_page.with_dom_common(_INSPECT_PAGE_JS))
        if isinstance(data, dict):
            data.setdefault("rejected", [])
            return data
    except Exception as exc:  # noqa: BLE001
        _log.debug("error inspecting page blockers: %s", exc)
    return {"errors": [], "unresolved": [], "rejected": [], "advance_disabled": False}
