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
  // Set when a tick may have revealed more fields; the fill runner then scans again.
  let revealed = false;

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
    const automationId = el.getAttribute("data-automation-id");
    if (automationId && document.querySelectorAll(`[data-automation-id="${CSS.escape(automationId)}"]`).length === 1) {
      return `${el.tagName.toLowerCase()}[data-automation-id="${automationId.replace(/"/g, '\\"')}"]`;
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
      if (label) return (label.innerText || label.textContent || "").trim();
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return aria.trim();
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      // A space-separated id list: the question plus, often, its hint or error text.
      const text = labelledBy.split(/\s+/).map(ref => document.getElementById(ref))
        .filter(Boolean).map(ref => (ref.innerText || ref.textContent || "").trim())
        .filter(Boolean).join(" ");
      if (text) return text;
    }
    // Workday: a questionnaire question lives in its form field's label/legend.
    const wdField = el.closest("[data-automation-id^='formField-']");
    if (wdField) {
      const title = wdField.querySelector("label, legend");
      const text = title ? (title.innerText || title.textContent || "").trim() : "";
      if (text) return text;
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

  /** A phone prefix is a distinct field even when the widget is called country. */
  function phoneCodeControl(el, label) {
    const clues = `${label} ${el.id} ${el.name || ""} ${el.getAttribute("autocomplete") || ""}`.toLowerCase();
    if (/tel-country-code|dial(?:ling|ing)?[ _-]*code|calling[ _-]*code|phone[ _-]*country|country[ _/-]*code/.test(clues)) return true;
    if (!/country/.test(clues)) return false;
    if (el.tagName !== "SELECT" && el.getAttribute("role") !== "combobox") return false;
    const group = el.closest("fieldset, [class*='phone' i], [data-field*='phone' i], .form-group");
    const nearPhone = group && group.querySelector("input[type='tel'], input[name*='phone' i]");
    if (nearPhone && el.getAttribute("role") === "combobox" &&
        /phone/i.test(`${group.className || ""} ${group.getAttribute("data-field") || ""}`)) return true;
    const options = el.tagName === "SELECT" ? Array.from(el.options) : [];
    const codes = options.filter(o => /\+\d{1,4}\b/.test(o.textContent || ""));
    return Boolean(nearPhone && codes.length >= 2);
  }

  /** Match a field key via hints, autocomplete attrs, then label synonyms. */
  function matchKey(el, label) {
    if (/^end[-_ ]?year(?:--\d+)?$/i.test(el.id || "")) return "graduation_month";
    if (/^start[-_ ]?year(?:--\d+)?$/i.test(el.id || "")) return "education_start_month";
    if (phoneCodeControl(el, label)) return "phone_country_code";
    // Workday's preferred-name block: the checkbox that reveals it, then its inputs,
    // whose own labels read plain "First Name" / "Last Name".
    const elId = el.id || "";
    if (/preferred/i.test(elId)) {
      if (el.type === "checkbox") return "has_preferred_name";
      if (/first/i.test(elId)) return "preferred_name";
      if (/last/i.test(elId)) return "last_name";
    }
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
    // A long free-text question ("Indicate any other names under which your school or
    // employment records may be identified") is not the School field just because it
    // says "school": short-field synonyms only apply to short text labels.
    const textLike = el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !["checkbox", "radio"].includes(el.type));
    if (textLike && label.length > 60) return null;
    const haystack = `${label} ${auto} ${el.getAttribute("name") || ""}`.toLowerCase();
    if (/future/.test(haystack) && /sponsor/.test(haystack)) return "requires_sponsorship_future";
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
    const prev = el.value;
    if (el.tagName === "TEXTAREA" && textareaValueSetter) {
      textareaValueSetter.call(el, str);
    } else if (inputValueSetter) {
      inputValueSetter.call(el, str);
    } else {
      el.value = str;
    }
    const tracker = el._valueTracker;
    if (tracker) {
      tracker.setValue(prev);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function norm(value) {
    return String(value || "").toLowerCase().normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9+]+/g, " ").trim().replace(/\s+/g, " ");
  }

  function selectByText(selectEl, value, key) {
    const options = Array.from(selectEl.options).filter(o => !o.disabled && String(o.value).trim() && !/^(select|choose|please select)/i.test(o.text.trim()));
    let matches = [];
    const target = norm(value);
    if (key === "phone_country_code") {
      const escaped = String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const code = new RegExp(`(^|[^0-9])${escaped}(?![0-9])`);
      matches = options.filter(o => code.test(o.text) || norm(o.value) === target);
      const region = norm(fields.phone_country_region);
      if (!matches.length && region) {
        const knownCodes = { "united states": "+1", us: "+1", canada: "+1", ca: "+1", "united kingdom": "+44", gb: "+44" };
        if (knownCodes[region] === String(value)) {
          matches = options.filter(o => {
            const codeLabel = /^[a-z]{2}$/i.test(o.value) ? new Intl.DisplayNames(["en"], { type: "region" }).of(o.value.toUpperCase()) : "";
            return norm(o.text) === region || norm(o.value) === region || norm(codeLabel) === region;
          });
        }
      }
      if (matches.length > 1) {
        matches = region ? matches.filter(o => norm(o.text).includes(region) || norm(o.value) === region) : matches.filter(o => norm(o.text) === target);
      }
    } else {
      matches = options.filter(o => norm(o.text) === target || norm(o.value) === target);
      if (!matches.length) {
        const aliases = {
          "united states": ["usa", "us", "united states of america"],
          "decline": ["decline to self identify", "prefer not to say", "i prefer not to say"],
          "bachelor": ["bachelors degree", "bachelor of science", "bachelor of arts"],
        };
        const alternatives = aliases[target] || [];
        matches = options.filter(o => alternatives.includes(norm(o.text)) || alternatives.includes(norm(o.value)));
      }
    }
    if (matches.length !== 1) return null;
    const opt = matches[0];
    selectEl.value = opt.value;
    selectEl.dispatchEvent(new Event("input", { bubbles: true }));
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    return selectEl.value === opt.value ? opt.text.trim() : null;
  }

  /** Click a radio/checkbox whose label matches the desired value. */
  function fillChoiceGroup(el, value, label) {
    const val = norm(value);
    const name = el.name;
    const single = el.type === "checkbox" &&
      (!name || document.querySelectorAll(`input[type="checkbox"][name="${CSS.escape(name)}"]`).length === 1);
    if (single) {
      // A lone checkbox is a yes/no switch ("I have a preferred name").
      if (!["yes", "true", "1", "no", "false", "0"].includes(val)) return false;
      const shouldCheck = ["yes", "true", "1"].includes(val);
      if (el.checked !== shouldCheck) {
        el.click();
        if (el.checked !== shouldCheck && el.id) document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.click();
        if (shouldCheck) revealed = true;
      }
      return el.checked === shouldCheck;
    }
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
        if (lbl) text = (lbl.innerText || lbl.textContent || "").trim();
      }
      const candidates = [norm(text), norm(input.value)];
      if (candidates.includes(val) || (val === "yes" && candidates.includes("1")) || (val === "no" && candidates.includes("0"))) {
        if (el.type === "checkbox") {
          const shouldCheck = val === "yes" || val === "true" || val === "1";
          if (input.checked !== shouldCheck) input.click();
        } else if (!input.checked) {
          input.click();
        }
        return true;
      }
    }
    return false;
  }

  // Always collect file inputs, even when styled with .visually-hidden or opacity: 0.
  /** Nearest enclosing section heading (Workday: "Resume/CV" above an unlabeled drop zone). */
  function sectionHeading(el) {
    let node = el;
    for (let depth = 0; depth < 10 && node; depth++) {
      node = node.parentElement;
      const heading = node && node.querySelector("h2, h3, h4, legend");
      if (heading) return (heading.innerText || heading.textContent || "").trim();
    }
    return "";
  }

  for (const fileEl of document.querySelectorAll('input[type="file"]')) {
    const fileSel = selectorFor(fileEl);
    const fileLbl = labelFor(fileEl) || sectionHeading(fileEl);
    if (!file_inputs.some((f) => f.selector === fileSel)) {
      file_inputs.push({ selector: fileSel, label: fileLbl });
    }
  }

  const controls = Array.from(
    document.querySelectorAll("input, select, textarea")
  ).filter(isVisible);

  for (const el of controls) {
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    const label = labelFor(el);
    const sel = selectorFor(el);
    const required = el.required || el.getAttribute("aria-required") === "true";

    if (type === "file" || skipTypes.has(type)) continue;
    // Workday: a honeypot "for robots only" input, and the search box of a multiselect
    // prompt (typing there does not commit a choice; the fill runner owns those).
    if (el.getAttribute("data-automation-id") === "beecatcher") continue;
    if (el.closest("[data-automation-id='multiselectInputContainer']")) continue;
    const key = matchKey(el, label);
    if (el.getAttribute("role") === "combobox") {
      const selectedText = (el.closest(".select__control, [class*='-control']")?.querySelector(".select__single-value, [class*='-singleValue']")?.textContent || "").trim();
      if (selectedText) {
        filled.push({ key: "existing", label, value: selectedText, selector: sel, preserved: true });
        continue;
      }
      leftovers.push({ key, label, type: "combobox", options: [], required, selector: sel, reason: "Custom dropdown needs an observed selection" });
      if (required) required_empty.push(label || sel);
      continue;
    }
    const selected = el.tagName === "SELECT" ? el.selectedOptions[0] : null;
    const existingAnswer = el.tagName === "SELECT"
      ? (selected && selected.value && !/^(select|choose|please select)/i.test(selected.text.trim()) ? selected.text.trim() : "")
      : ((type === "checkbox" || type === "radio") ? "" : String(el.value || "").trim());
    if (existingAnswer) {
      filled.push({ key: "existing", label, value: existingAnswer, selector: sel, preserved: true });
      continue;
    }
    if ((type === "checkbox" || type === "radio") && el.name && Array.from(document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)).some(input => input.checked)) {
      filled.push({ key: "existing", label, value: "selected", selector: sel, preserved: true });
      continue;
    }

    const salaryQuestion = /\b(salary|compensation|pay expectation|desired pay|pay rate|wages?)\b/i.test(label);
    if (salaryQuestion && (el.tagName === "TEXTAREA" || el.tagName === "INPUT")) {
      // The fill runner precomputes every unit/format variant (`apply/salary.py`).
      const unit = /\bhour/i.test(label) ? "salary_hourly" : /\b(year|annual)/i.test(label) ? "salary_yearly" : "salary_expectation";
      const numeric = type === "number" || ["numeric", "decimal"].includes(el.getAttribute("inputmode") || "");
      const answer = fields[numeric ? `${unit}_number` : unit];
      if (!answer) {
        leftovers.push({ key: "salary_expectation", label, type, required, selector: sel, reason: "No salary range in the applicant profile" });
        if (required) required_empty.push(label || sel);
        continue;
      }
      setNativeValue(el, answer);
      filled.push({ key: "salary_expectation", label, value: String(answer), selector: sel });
      continue;
    }

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

    if (!key || key === "submit" || key === "resume_upload" || key === "confirmation_text") {
      const options =
        el.tagName === "SELECT"
          ? Array.from(el.options).map((o) => o.text.trim())
          : [];
      leftovers.push({
        label,
        type,
        options,
        reason: "Unrecognized field",
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
        reason: "No supported profile answer",
      });
      if (required) required_empty.push(label || sel);
      continue;
    }

    let written = "";
    if (el.tagName === "SELECT") {
      written = selectByText(el, value, key) || "";
      if (!written) {
        leftovers.push({ label, type, options: Array.from(el.options).map((o) => o.text.trim()), required, selector: sel, reason: "No unique matching option" });
        if (required) required_empty.push(label || sel);
        continue;
      }
    } else if (type === "radio" || type === "checkbox") {
      if (!fillChoiceGroup(el, value, label)) {
        leftovers.push({ label, type, options: [], required, selector: sel, reason: "No exact matching choice" });
        if (required) required_empty.push(label || sel);
        continue;
      }
      written = String(value);
    } else {
      let textValue = String(value);
      if (key === "graduation_month" && /end[-_ ]?year/i.test(el.id || label)) textValue = textValue.slice(0, 4);
      if (key === "education_start_month" && /start[-_ ]?year/i.test(el.id || label)) textValue = textValue.slice(0, 4);
      if (key === "earliest_start" && /^\d{4}-\d{2}-\d{2}$/.test(textValue) && type !== "date") {
        const [year, month, day] = textValue.split("-").map(Number);
        textValue = `${new Intl.DateTimeFormat("en-US", { month: "long" }).format(new Date(Date.UTC(year, month - 1, day)))} ${day}, ${year}`;
      }
      const workdayPhoneCode = document.querySelector("[data-automation-id='formField-countryPhoneCode']");
      if (key === "phone" && fields.phone_country_code && (workdayPhoneCode ||
          (el.getAttribute("type") === "tel" &&
           Array.from(document.querySelectorAll("select,[role='combobox']")).some(other => phoneCodeControl(other, labelFor(other)))))) {
        const code = String(fields.phone_country_code);
        if (textValue.startsWith(code)) textValue = textValue.slice(code.length).replace(/^[\s()\-.]+/, "");
      }
      setNativeValue(el, textValue);
      written = textValue;
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
    revealed,
  };
}
