/**
 * fill_probe readback (eval-only): every visible form control on this frame as the page
 * shows it now, { label, kind, required, shown, invalid, message }. Run only on the made-up
 * applicant's pages, so the shown values may be recorded.
 */
() => {
  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  /*DOM_COMMON*/

  function text(node) {
    return (node?.innerText || node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function labelFor(el) {
    const root = rootOf(el);
    if (el.id) {
      const label = root.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label && text(label)) return text(label);
    }
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map((id) => text(root.getElementById(id))).filter(Boolean);
      if (parts.length) return parts.join(" ");
    }
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();
    const wrap = el.closest("label");
    if (wrap && text(wrap)) return text(wrap);
    const field = el.closest("[data-automation-id^='formField'], fieldset, .form-group, .field, [class*='question' i]");
    const legend = field?.querySelector("legend, label, [data-automation-id*='label']");
    if (legend && text(legend)) return text(legend);
    return (el.getAttribute("placeholder") || el.getAttribute("name") || "").trim();
  }

  function container(el) {
    return el.closest("[data-automation-id^='formField'], fieldset, .form-group, .field, .application-question, [class*='question' i], [class*='field' i]") || el.parentElement;
  }

  function message(el) {
    const root = rootOf(el);
    const ids = (el.getAttribute("aria-describedby") || "") + " " + (el.getAttribute("aria-errormessage") || "");
    for (const id of ids.split(/\s+/).filter(Boolean)) {
      const node = root.getElementById(id);
      const t = text(node);
      if (t && /error|invalid|required|must|please|enter a valid/i.test(t)) return t.slice(0, 200);
    }
    const box = container(el);
    const err = box?.querySelector("[role='alert'], [class*='error' i], [data-automation-id*='error' i], .invalid-feedback");
    return err && isVisible(err) ? text(err).slice(0, 200) : "";
  }

  function shown(el) {
    const type = (el.getAttribute("type") || el.tagName).toLowerCase();
    const workdayField = el.closest("[data-automation-id^='formField-']");
    if (workdayField) {
      const chips = Array.from(workdayField.querySelectorAll("[data-automation-id='selectedItem']")).map(text).filter(Boolean);
      if (chips.length) return chips.join("; ");
      const button = workdayField.querySelector("button[aria-haspopup='listbox']");
      if (button && el === button) return text(button).replace(/^select one$/i, "");
    }
    const box = reactSelectBox(el);
    if (box) {
      const values = Array.from(box.querySelectorAll("[class*='singleValue'], [class*='single-value'], [class*='multiValue'] [class*='label'], [class*='multi-value__label']")).map(text);
      return values.filter(Boolean).join("; ");
    }
    if (el.tagName === "SELECT") {
      const option = el.selectedOptions[0];
      return option && el.value ? text(option) : "";
    }
    if (type === "checkbox" || type === "radio") return el.checked ? "checked" : "";
    if (el.matches("[role='combobox'], [aria-haspopup='listbox']") && !("value" in el)) return text(el);
    return String(el.value || "").trim();
  }

  const rows = [];
  const seenGroups = new Set();
  const controls = deepQueryAll(document, "input, select, textarea, [role='combobox'], button[aria-haspopup='listbox']");
  for (const el of controls) {
    const type = (el.getAttribute("type") || "").toLowerCase();
    if (["hidden", "submit", "button", "image", "reset", "search"].includes(type)) continue;
    if (honeypot(el) || twinOwner(el) || !isVisible(el)) continue;
    if (el.closest("[role='listbox'], [class*='-menu'], [class*='select__menu']")) continue;
    const required = el.required || el.getAttribute("aria-required") === "true";
    const invalid = el.getAttribute("aria-invalid") === "true" || (el.willValidate && !el.validity.valid && !el.validity.valueMissing);
    if (type === "radio" || type === "checkbox") {
      const name = el.name;
      const key = `${type}:${name || el.id}`;
      if (name && seenGroups.has(key)) continue;
      const group = name ? Array.from(rootOf(el).querySelectorAll(`input[type="${type}"][name="${CSS.escape(name)}"]`)) : [el];
      if (name) seenGroups.add(key);
      const checked = group.filter((input) => input.checked).map((input) => labelFor(input));
      const groupBox = el.closest("fieldset, [role='radiogroup'], [role='group'], [data-automation-id^='formField']");
      const label = group.length > 1 ? text(groupBox?.querySelector("legend, label:not([for]), [data-automation-id*='label']")) || labelFor(el) : labelFor(el);
      rows.push({ label: label.slice(0, 160), kind: type, required, shown: checked.join("; ").slice(0, 200), invalid, message: message(el) });
      continue;
    }
    if (type === "file") {
      rows.push({ label: labelFor(el).slice(0, 160), kind: "file", required, shown: el.files?.length ? "file" : "", invalid, message: message(el) });
      continue;
    }
    rows.push({
      label: labelFor(el).slice(0, 160),
      kind: el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea" : el.matches(TRIGGERS) ? "dropdown" : type || "text",
      required,
      shown: shown(el).slice(0, 200),
      invalid: Boolean(invalid),
      message: message(el),
    });
  }
  const alerts = deepQueryAll(document, "[role='alert'], [data-automation-id='errorMessage'], [class*='error-summary' i]")
    .filter(isVisible).map(text).filter(Boolean).slice(0, 10);
  return { url: location.href, rows, alerts };
}
