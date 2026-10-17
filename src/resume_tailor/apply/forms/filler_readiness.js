/**
 * Return { required_empty, invalid }: labels of visible required controls that are still
 * empty, and of visible controls whose value the form rejects (native validity or
 * aria-invalid). With { revalidate: true }, rejected controls are focused, changed and
 * blurred first, so a marker left over from before the fill typed the value can clear.
 */
(args) => {
  const empty = [];
  const invalid = [];
  const skipTypes = new Set(["hidden", "file", "submit", "button", "image", "reset"]);

  function isVisible(el) {
    if (!el || el.disabled) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  /** The document or shadow root holding el (see filler.js). */
  function rootOf(el) {
    const root = el.getRootNode();
    return root && typeof root.querySelectorAll === "function" ? root : document;
  }

  /** querySelectorAll that also searches open shadow roots, in document order. */
  function deepQueryAll(root, sel) {
    const out = [];
    for (const node of root.querySelectorAll("*")) {
      if (node.matches(sel)) out.push(node);
      if (node.shadowRoot) out.push(...deepQueryAll(node.shadowRoot, sel));
    }
    return out;
  }

  function labelFor(el) {
    const id = el.id;
    const root = rootOf(el);
    if (id) {
      const label = root.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (label) return (label.innerText || label.textContent || "").trim();
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const ref = root.getElementById(labelledBy.split(/\s+/)[0]);
      if (ref) return (ref.innerText || ref.textContent || "").trim();
    }
    const placeholder = el.getAttribute("placeholder");
    if (placeholder) return placeholder.trim();
    const name = el.getAttribute("name");
    if (name) return name.trim();
    return "";
  }

  function groupLabel(el) {
    const group = el.closest("fieldset, [role='radiogroup'], [data-automation-id*='formField'], .form-group, [class*='question' i]");
    if (group) {
      const label = group.querySelector("legend, [data-automation-id*='label'], .field-label, label:not([for])");
      const text = (label?.innerText || label?.textContent || "").trim();
      if (text) return text;
    }
    return el.name || el.id || "Choice group";
  }

  function isEmpty(el) {
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    // Workday multiselect prompt: the search box stays empty; the answer is a chip.
    if (el.closest("[data-automation-id='multiselectInputContainer']")) {
      const field = el.closest("[data-automation-id^='formField-']");
      return !field?.querySelector("[data-automation-id='selectedItem']");
    }
    if (el.getAttribute("role") === "combobox") {
      const container = el.closest(".select__control, [class*='-control'], [data-automation-id*='formField']");
      return !container?.querySelector(".select__single-value, [class*='-singleValue'], .select__multi-value, [class*='-multiValue'], [data-automation-id*='selected']");
    }
    if (type === "checkbox" || type === "radio") {
      const name = el.name;
      if (!name) return !el.checked;
      const group = rootOf(el).querySelectorAll(
        `input[type="${type}"][name="${name.replace(/"/g, '\\"')}"]`
      );
      return !Array.from(group).some((input) => input.checked);
    }
    if (el.tagName === "SELECT") {
      const selected = el.selectedOptions[0];
      return !el.value || !selected || selected.disabled || /^(select|choose|please select)/i.test(selected.text.trim());
    }
    return !String(el.value || "").trim();
  }

  /** A Lever custom question from its card's `baseTemplate` JSON (see filler.js). */
  function leverQuestion(el) {
    const match = /^cards\[([^\]]+)\]\[field(\d+)\]/.exec(el.getAttribute("name") || "");
    if (!match) return null;
    const template = rootOf(el).querySelector(`input[name="cards[${CSS.escape(match[1])}][baseTemplate]"]`);
    try {
      const field = JSON.parse(template?.value || "null")?.fields?.[Number(match[2])];
      return field && typeof field.text === "string" ? field : null;
    } catch {
      return null;
    }
  }

  /** The form holds a value here and refuses it; an empty field is `isEmpty`'s case. */
  function isRejected(el, type) {
    if (type === "checkbox" || type === "radio" || isEmpty(el)) return false;
    if (el.getAttribute("aria-invalid") === "true") return true;
    return !!el.validity && !el.validity.valid && !el.validity.valueMissing;
  }

  function revalidate(el) {
    el.focus({ preventScroll: true });
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.blur();
  }

  const seenGroups = new Set();
  for (const [index, el] of deepQueryAll(document, "input, select, textarea").entries()) {
    if (!isVisible(el)) continue;
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    if (skipTypes.has(type)) continue;
    // React Select's internal required/search inputs belong to the parent question.
    if (el.closest('.select__control, [class*="-control"]') && el.getAttribute('role') !== 'combobox') continue;
    const lever = leverQuestion(el);
    if (isRejected(el, type)) {
      if (args?.revalidate) revalidate(el);
      invalid.push(lever?.text.trim() || labelFor(el) || el.id || el.getAttribute("name") || `Unlabeled field ${index + 1}`);
      continue;
    }
    const required = el.required || el.getAttribute("aria-required") === "true" || lever?.required === true;
    if (!required) continue;
    if ((type === "radio" || type === "checkbox") && el.name) {
      const groupKey = `${type}:${el.name}`;
      if (seenGroups.has(groupKey)) continue;
      seenGroups.add(groupKey);
    }
    if (isEmpty(el)) {
      const label = lever?.text.trim() ||
        (type === "radio" || type === "checkbox" ? groupLabel(el) : labelFor(el));
      empty.push(label || el.id || el.getAttribute("name") || `Unlabeled required field ${index + 1}`);
    }
  }

  // Workday single-select dropdowns are buttons, not form controls.
  for (const button of document.querySelectorAll("button[aria-haspopup='listbox']")) {
    if (!isVisible(button) || !button.closest("[data-automation-id^='formField-']")) continue;
    if (!/\bRequired\b/.test(button.getAttribute("aria-label") || "")) continue;
    if (/^\s*(select one|select|choose one)?\s*$/i.test(button.innerText || "")) {
      const label = button.id && document.querySelector(`label[for="${CSS.escape(button.id)}"]`);
      empty.push(((label && label.innerText) || button.getAttribute("aria-label") || button.id).replace(/\*\s*$/, "").trim());
    }
  }

  return { required_empty: empty, invalid: [...new Set(invalid)] };
}
