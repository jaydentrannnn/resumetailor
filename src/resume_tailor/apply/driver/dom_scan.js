/** Read-only application control snapshot, evaluated once for each Playwright frame. */
() => {
  const visible = (el) => {
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && box.width > 0 && box.height > 0;
  };
  const css = (value) => CSS.escape(String(value));
  const text = (el) => (el?.innerText || el?.textContent || "").trim();
  const selector = (el) => {
    if (el.id && document.querySelectorAll(`#${css(el.id)}`).length === 1) return `#${css(el.id)}`;
    const pieces = [];
    for (let node = el; node?.nodeType === 1; node = node.parentElement) {
      let part = node.tagName.toLowerCase();
      if (node.id && document.querySelectorAll(`#${css(node.id)}`).length === 1) {
        pieces.unshift(`#${css(node.id)}`);
        break;
      }
      const siblings = node.parentElement ? Array.from(node.parentElement.children).filter(child => child.tagName === node.tagName) : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      pieces.unshift(part);
      if (node === document.documentElement) break;
    }
    return pieces.join(" > ");
  };
  const label = (el) => {
    const refs = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)
      .map(id => text(document.getElementById(id))).filter(Boolean);
    if (refs.length) return refs.join(" ");
    if (el.labels?.length) return Array.from(el.labels).map(text).filter(Boolean).join(" ");
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label").trim();
    return text(el.closest("label")) || el.getAttribute("placeholder") || el.getAttribute("name") || "";
  };
  const group = (el) => el.closest("fieldset, [role='radiogroup'], [class*='question' i], [data-automation-id*='formField' i], .form-group");
  const section = (el) => {
    const parent = group(el);
    let node = el.parentElement;
    for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
      const heading = node.querySelector(":scope > legend, :scope > h2, :scope > h3, :scope > h4, :scope > [role='heading']");
      if (heading && /preferred name|legal name/i.test(text(heading))) return text(heading);
    }
    return text(parent?.querySelector("legend, h2, h3, [class*='label' i]")) || parent?.getAttribute("class") || "";
  };
  const placeholder = (option) => !String(option.value || "").trim() || /^(select|choose|please select)\b/i.test(text(option));
  const kind = (el) => {
    const role = el.getAttribute("role");
    if (el.tagName === "SELECT") return el.multiple ? "multiselect" : "native_select";
    if (role === "combobox" || el.getAttribute("aria-haspopup") === "listbox") return "combobox";
    if (el.tagName === "TEXTAREA") return "textarea";
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (type === "radio") return "radio_group";
    if (type === "checkbox") return "checkbox";
    if (type === "file") return "file";
    if (type === "date" || type === "number") return type;
    if (["text", "email", "tel", "url", "search"].includes(type)) return "text";
    return "unsupported";
  };
  const controls = Array.from(document.querySelectorAll("input, select, textarea, button[role='combobox'], button[aria-haspopup='listbox']"));
  // Modern Greenhouse replaces a successful upload input with a filename.
  // Keep that component observable so Continue can preserve the attachment.
  for (const upload of document.querySelectorAll(".file-upload")) {
    if (!upload.querySelector("input[type='file']") && upload.querySelector(".file-upload__filename")) controls.push(upload);
  }
  const seenRadio = new Set();
  const fields = [];
  for (const el of controls) {
    if (el.getAttribute("data-automation-id") === "beecatcher") continue;
    const controlKind = el.matches(".file-upload") ? "file" : kind(el);
    if (controlKind === "unsupported") continue;
    if (controlKind !== "file" && !visible(el)) continue;
    if (controlKind === "radio_group" && el.name) {
      if (seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
    }
    const path = selector(el);
    const nativeOptions = el.tagName === "SELECT" ? Array.from(el.options) : [];
    const radioOptions = controlKind === "radio_group" && el.name
      ? Array.from(document.querySelectorAll(`input[type='radio'][name='${css(el.name)}']`)) : [];
    const options = (nativeOptions.length ? nativeOptions : radioOptions).map((option, index) => ({
      option_id: `${path}::${index}`,
      label: label(option) || text(option),
      value: option.value || "",
      enabled: !option.disabled,
      placeholder: nativeOptions.length ? placeholder(option) : false,
      selected: nativeOptions.length ? option.selected : option.checked,
    }));
    const selectedText = text(el.closest(".select__control, [class*='-control']")?.querySelector(".select__single-value, [class*='-singleValue']"));
    const uploadFilename = text(el.closest(".file-upload")?.querySelector(".file-upload__filename"));
    const current = controlKind === "combobox" ? selectedText : controlKind === "radio_group"
      ? (options.find(option => option.selected)?.label || "")
      : controlKind === "checkbox" ? (el.checked ? "checked" : "")
      : controlKind === "file" ? (el.files?.[0]?.name || uploadFilename || "")
      : controlKind === "native_select" ? (options.find(option => option.selected && !option.placeholder)?.label || "")
      : (el.value || "");
    const parent = group(el);
    const uploadLabel = text(el.closest(".file-upload")?.querySelector(".upload-label"));
    const errors = parent ? Array.from(parent.querySelectorAll("[role='alert'], [class*='error' i], [aria-invalid='true']")).map(text).filter(Boolean) : [];
    fields.push({
      field_id: path, selector: path, document_generation: String(performance.timeOrigin),
      section_id: section(el), repeater_row_id: parent?.getAttribute("data-automation-id") ||
        (/^(?:school|degree|discipline|end-year|start-year)--(\d+)$/.exec(el.id || "")?.[1] ?? ""),
      label: el.matches(".file-upload") ? uploadLabel :
        controlKind === "radio_group" ? text(parent?.querySelector("legend")) || label(el) : label(el),
      help_text: text(parent?.querySelector("[class*='help' i], [aria-describedby]")),
      control_kind: controlKind, required: Boolean(el.required || el.getAttribute("aria-required") === "true" || (controlKind === "file" && /\*$/.test(uploadLabel))),
      enabled: !el.disabled, visible: visible(el), current_value: String(current).trim(),
      selection_state: controlKind === "combobox" ? (selectedText ? "committed" : "unselected") : "",
      options, validation_messages: errors,
      constraints: {
        name: el.getAttribute("name") || "", id: el.id || "",
        input_type: el.getAttribute("type") || "", autocomplete: el.getAttribute("autocomplete") || "",
        automation_id: el.getAttribute("data-automation-id") || "",
        max_length: el.maxLength > 0 ? el.maxLength : null, accept: el.getAttribute("accept") || "",
        phone_sibling: Boolean(parent?.querySelector("input[type='tel'], input[name*='phone' i]")),
      },
    });
  }
  return { document_generation: String(performance.timeOrigin), url: location.href, fields };
}
