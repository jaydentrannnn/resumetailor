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
