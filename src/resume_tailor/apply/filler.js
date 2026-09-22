/**
 * Deterministic ATS form filler — injected via Playwright page.evaluate.
 * Receives { fields, hints, synonyms } and returns fill diagnostics.
 */
({ fields, hints, synonyms }) => {
  const filled = [];
  const leftovers = [];
  const long_text = [];
  const file_inputs = [];
  const required_empty = [];

  const skipTypes = new Set(["hidden", "file", "submit", "button", "image", "reset"]);
  const frames_skipped = document.querySelectorAll("iframe").length;

  const inputValueSetter =
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
  const textareaValueSetter =
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")?.set;

  /** Return true when an element is visible and enabled. */
  function isVisible(el) {
    if (!el || el.disabled) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  /** Build a CSS selector that uniquely identifies el among peers. */
  function selectorFor(el) {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const name = el.getAttribute("name");
    if (name) {
      const tag = el.tagName.toLowerCase();
      return `${tag}[name="${name.replace(/"/g, '\\"')}"]`;
    }
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 4) {
      let part = node.tagName.toLowerCase();
      if (node.id) {
        part += `#${CSS.escape(node.id)}`;
        parts.unshift(part);
        break;
      }
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(
          (c) => c.tagName === node.tagName
        );
        if (siblings.length > 1) {
          part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
        }
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ");
  }

  /** Resolve human-readable label text for a control. */
  function labelFor(el) {
    const id = el.id;
    if (id) {
      const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (label) return label.innerText.trim();
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const ref = document.getElementById(labelledBy);
      if (ref) return ref.innerText.trim();
    }
    const placeholder = el.getAttribute("placeholder");
    if (placeholder) return placeholder.trim();
    const name = el.getAttribute("name");
    if (name) return name.trim();
    return "";
  }

  /** Normalise synonym entries to [pattern, key] pairs. */
  function normaliseSynonyms(list) {
    const out = [];
    for (const item of list || []) {
      if (Array.isArray(item) && item.length >= 2) {
        out.push([String(item[0]), String(item[1])]);
      } else if (item && typeof item === "object" && item.pattern && item.key) {
        out.push([String(item.pattern), String(item.key)]);
      }
    }
    return out;
  }

  const synonymList = normaliseSynonyms(synonyms);

  /** Match a field key via hints, autocomplete attrs, then label synonyms. */
  function matchKey(el, label) {
    const sel = selectorFor(el);
    if (hints && hints[sel]) return hints[sel];

    for (const [hintSel, key] of Object.entries(hints || {})) {
      if (hintSel === "confirmation_text" || hintSel === "submit") continue;
      try {
        if (el.matches(hintSel)) return key;
      } catch (_) {
        /* invalid selector — skip */
      }
    }

    const auto =
      el.getAttribute("autocomplete") ||
      el.getAttribute("data-automation-id") ||
      el.getAttribute("data-field") ||
      "";
    const haystack = `${label} ${auto} ${el.getAttribute("name") || ""}`.toLowerCase();
    for (const [pattern, key] of synonymList) {
      try {
        if (new RegExp(pattern, "i").test(haystack)) return key;
      } catch (_) {
        /* bad regex — skip */
      }
    }
    return null;
  }

  /** Dispatch input/change after programmatic value assignment. */
  function setNativeValue(el, value) {
    const str = String(value);
    if (el.tagName === "TEXTAREA" && textareaValueSetter) {
      textareaValueSetter.call(el, str);
    } else if (inputValueSetter) {
      inputValueSetter.call(el, str);
    } else {
      el.value = str;
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** Pick the best matching option text for a select control. */
  function selectByText(selectEl, value) {
    const target = String(value).toLowerCase();
    for (const opt of selectEl.options) {
      const text = opt.text.trim().toLowerCase();
      if (text === target || text.includes(target) || target.includes(text)) {
        selectEl.value = opt.value;
        selectEl.dispatchEvent(new Event("input", { bubbles: true }));
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        return opt.text.trim();
      }
    }
    return null;
  }

  /** Click a radio/checkbox whose label matches the desired value. */
  function fillChoiceGroup(el, value, label) {
    const val = String(value).toLowerCase();
    const name = el.name;
    if (!name) return false;
    const group = document.querySelectorAll(
      `input[type="${el.type}"][name="${name.replace(/"/g, '\\"')}"]`
    );
    for (const input of group) {
      const inputLabel = labelFor(input);
      const id = input.id;
      let text = inputLabel;
      if (id) {
        const lbl = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        if (lbl) text = lbl.innerText.trim();
      }
      const candidate = `${text} ${input.value}`.toLowerCase();
      if (
        candidate.includes(val) ||
        (val === "yes" && (input.value === "1" || input.value.toLowerCase() === "yes")) ||
        (val === "no" && (input.value === "0" || input.value.toLowerCase() === "no"))
      ) {
        input.click();
        return true;
      }
    }
    return false;
  }

  const controls = Array.from(
    document.querySelectorAll("input, select, textarea")
  ).filter(isVisible);

  for (const el of controls) {
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    const label = labelFor(el);
    const sel = selectorFor(el);
    const required = el.required || el.getAttribute("aria-required") === "true";

    if (type === "file") {
      file_inputs.push({ selector: sel, label });
      continue;
    }

    if (skipTypes.has(type)) continue;

    if (el.tagName === "TEXTAREA") {
      const maxLen = el.maxLength > 0 ? el.maxLength : null;
      const rows = parseInt(el.getAttribute("rows") || "2", 10);
      if ((maxLen !== null && maxLen > 200) || (maxLen === null && rows >= 3)) {
        long_text.push({
          label,
          selector: sel,
          maxlength: maxLen,
        });
        continue;
      }
    }

    const key = matchKey(el, label);
    if (!key || key === "submit" || key === "resume_upload" || key === "confirmation_text") {
      const options =
        el.tagName === "SELECT"
          ? Array.from(el.options).map((o) => o.text.trim())
          : [];
      leftovers.push({
        label,
        type,
        options,
        required,
        selector: sel,
      });
      if (required && !el.value) {
        required_empty.push(label || sel);
      }
      continue;
    }

    const value = fields[key];
    if (value === undefined || value === null || String(value).trim() === "") {
      leftovers.push({
        label,
        type,
        options:
          el.tagName === "SELECT"
            ? Array.from(el.options).map((o) => o.text.trim())
            : [],
        required,
        selector: sel,
      });
      if (required) required_empty.push(label || sel);
      continue;
    }

    let written = "";
    if (el.tagName === "SELECT") {
      written = selectByText(el, value) || "";
      if (!written) {
        leftovers.push({ label, type, options: Array.from(el.options).map((o) => o.text.trim()), required, selector: sel });
        if (required) required_empty.push(label || sel);
        continue;
      }
    } else if (type === "radio" || type === "checkbox") {
      if (!fillChoiceGroup(el, value, label)) {
        leftovers.push({ label, type, options: [], required, selector: sel });
        if (required) required_empty.push(label || sel);
        continue;
      }
      written = String(value);
    } else {
      setNativeValue(el, value);
      written = String(value);
    }

    filled.push({ key, label, value: written, selector: sel });
  }

  return {
    filled,
    leftovers,
    long_text,
    file_inputs,
    required_empty,
    frames_skipped,
  };
}
