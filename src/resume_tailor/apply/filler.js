/**
 * Deterministic ATS form filler — injected via Playwright page.evaluate.
 * Receives { fields, hints, synonyms, eeo } and returns fill diagnostics; ``eeo`` maps
 * a self-identification key to the regex (over ``norm``ed option text) that picks its
 * answer (`field_matcher.eeo_patterns`).
 */
({ fields, hints, synonyms, eeo = {} }) => {
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
    const container = containerLabel(el);
    if (container) return container;
    const placeholder = el.getAttribute("placeholder");
    if (placeholder && !GENERIC_PLACEHOLDER.test(placeholder.trim())) return placeholder.trim();
    const name = el.getAttribute("name");
    if (name) return name.trim();
    return "";
  }

  /** Keys of short identity/address/education fields, never of a long question. */
  const SHORT_FIELD_KEYS = new Set([
    "first_name", "middle_name", "last_name", "preferred_name", "email", "phone", "address_line1",
    "address_line2", "city", "state", "postal_code", "country", "school", "major", "degree_level", "gpa",
    "website", "current_company", "current_title", "linkedin_url", "github_url", "portfolio_url",
  ]);

  /** "Enter" / "Select" / "YYYY" say how to type, not what the field is. */
  const GENERIC_PLACEHOLDER = /^(enter|select|select\.\.\.|choose|type here|search|yyyy|mm|dd)$/i;

  /**
   * Question text that sits as bare text in the ancestors holding only this control (a
   * radio/checkbox group counts as one control) — Epic Games' form has no <label for>,
   * no aria, and placeholder "Enter". The widget's own text (option labels, a React
   * Select placeholder, an upload drop zone) is removed, then "*" / ":" markers.
   */
  function containerLabel(el) {
    const group = (el.type === "radio" || el.type === "checkbox") && el.name ? el.name : "";
    const sameControl = (other) => other === el || (group && other.name === group && other.type === el.type);
    let node = el.parentElement;
    let best = "";
    for (let depth = 0; node && node !== document.body && depth < 12; depth++, node = node.parentElement) {
      const controls = node.querySelectorAll("input:not([type='hidden']), select, textarea");
      if (Array.from(controls).some((other) => !sameControl(other))) break;
      const clone = node.cloneNode(true);
      // An option's own label (wrapping a group member, or `for` one) is not the question.
      const memberIds = new Set(Array.from(controls).map((c) => c.id).filter(Boolean));
      clone.querySelectorAll("label").forEach((n) => {
        if (n.querySelector("input") || memberIds.has(n.getAttribute("for") || "")) n.remove();
      });
      // Widgets, validation messages ("This section is required") and screen-reader
      // live regions ("0 results available") are not part of the question.
      clone.querySelectorAll(
        "input, select, textarea, option, [class*='-control'], [class*='-menu'], [aria-live], [role='alert'], " +
        "[class*='error' i], [id*='error' i], [class*='a11yText' i]"
      ).forEach((n) => n.remove());
      const text = (clone.textContent || "").replace(/[⁠​]/g, "").replace(/\s+/g, " ").trim();
      if (text && !GENERIC_PLACEHOLDER.test(text)) best = text;
    }
    return best.replace(/\s*\*?\s*:?\s*$/, "").trim();
  }

  /** The visible text of one radio/checkbox option (not its question). */
  function optionText(input) {
    if (input.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (lbl) return (lbl.innerText || lbl.textContent || "").trim();
    }
    const wrap = input.closest("label");
    if (wrap) return (wrap.innerText || wrap.textContent || "").trim();
    return (input.getAttribute("aria-label") || input.value || "").trim();
  }

  /** React Select: an input inside a "-control" box with a placeholder/value sibling. */
  function isReactSelect(el) {
    if (el.tagName !== "INPUT") return false;
    if (/^react-select-.*-input$/.test(el.id || "")) return true;
    const control = el.closest("[class*='-control']");
    return Boolean(control && control.querySelector("[class*='-placeholder'], [class*='-singleValue'], [class*='single-value']"));
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
    // Epic Games / Greenhouse-style education rows: educations[0].start_date.year. Decided
    // here so "start date" never reaches the availability synonym (earliest_start).
    const eduDate = /educations?\[\d+\]\.(start|end)_date\.(?:year|month)$/i.exec(el.getAttribute("name") || "");
    if (eduDate) return eduDate[1].toLowerCase() === "start" ? "education_start_month" : "graduation_month";
    const educationContext = `${el.id || ""} ${el.closest("fieldset, [data-automation-id*='education' i]")?.textContent?.slice(0, 100) || ""}`;
    if (/education|university|school/i.test(educationContext)) {
      if (/first year attended|education start year|university start year|start year/i.test(label)) return "education_start_month";
      if (/last year attended|education end year|graduation year|end year/i.test(label)) return "graduation_month";
    }
    if (phoneCodeControl(el, label)) return "phone_country_code";
    // Workday's preferred-name block: the checkbox that reveals it, then its inputs,
    // whose own labels read plain "First Name" / "Last Name".
    const elId = el.id || "";
    const automation = `${el.getAttribute("data-automation-id") || ""} ${el.getAttribute("name") || ""}`;
    if (/preferred/i.test(`${elId} ${automation}`)) {
      if (el.type === "checkbox") return "has_preferred_name";
      if (/first/i.test(`${elId} ${automation}`)) return "preferred_name";
      if (/last/i.test(`${elId} ${automation}`)) return "last_name";
    }
    if (/preferred first name/i.test(label)) return "preferred_name";
    if (/preferred last name/i.test(label)) return "last_name";
    if (/^first name$/i.test(label.trim())) {
      let node = el.parentElement;
      for (let depth = 0; node && depth < 5; depth++, node = node.parentElement) {
        const heading = node.querySelector(":scope > legend, :scope > h2, :scope > h3, :scope > h4, :scope > [role='heading']");
        if (heading && /preferred name/i.test(heading.textContent || "")) return "preferred_name";
        if (heading && /legal name/i.test(heading.textContent || "")) break;
      }
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
    // A dropdown's question is a choice, however long it is worded.
    const choiceWidget = el.getAttribute("role") === "combobox" || isReactSelect(el);
    const textLike = !choiceWidget && (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && !["checkbox", "radio"].includes(el.type)));
    if (textLike && label.length > 60) return null;
    // `questions.first_name` reads as "questions first name" to the synonyms.
    const name = el.getAttribute("name") || "";
    const haystack = `${label} ${auto} ${name} ${name.replace(/[._\-\[\]]+/g, " ")}`.toLowerCase();
    if (/future/.test(haystack) && /sponsor/.test(haystack) && !/\bnow\b|\bcurrent/.test(haystack)) return "requires_sponsorship_future";
    for (const [pattern, key] of synonymList) {
      // A long question that merely mentions "school" or "capacity" is a choice about
      // something else, not the School/City field.
      if (label.length > 60 && SHORT_FIELD_KEYS.has(key)) continue;
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

  // Mirrors field_matcher.degree_of: "BS", "B.S.", "BSc" and "Bachelor of Science (B.S.)"
  // are one degree; "Bachelor's Degree" is the level alone.
  const DEGREES = {
    "bachelor of science": ["bs", "b s", "bsc", "b sc"],
    "bachelor of arts": ["ba", "b a"],
    "bachelor of science in engineering": ["bse", "b s e"],
    "bachelor of engineering": ["be", "b e", "beng", "b eng"],
    "bachelor of fine arts": ["bfa", "b f a"],
    "bachelor of business administration": ["bba", "b b a"],
    "master of science": ["ms", "m s", "msc", "m sc"],
    "master of arts": ["ma", "m a"],
    "master of engineering": ["meng", "m eng"],
    "master of business administration": ["mba", "m b a"],
    "doctor of philosophy": ["phd", "ph d"],
    "associate of science": ["as", "a s"],
    "associate of arts": ["aa", "a a"],
  };
  const DEGREE_LEVELS = {
    bachelor: "bachelor", bachelors: "bachelor", "bachelor s": "bachelor",
    master: "master", masters: "master", "master s": "master",
    associate: "associate", associates: "associate", "associate s": "associate",
    doctorate: "doctor", doctoral: "doctor",
  };
  function degreePart(text) {
    const wanted = norm(text).replace(/\s+degree$/, "");
    if (DEGREES[wanted]) return [wanted.split(" ")[0], wanted];
    for (const [name, abbrs] of Object.entries(DEGREES)) {
      if (abbrs.includes(wanted)) return [name.split(" ")[0], name];
    }
    const subject = /^(\w+ of [\w ]+?) in \w/.exec(wanted);
    if (subject && DEGREES[subject[1]]) return [subject[1].split(" ")[0], subject[1]];
    const prefixes = Object.entries(DEGREES).flatMap(([name, abbrs]) => abbrs.map(a => [a, name]))
      .sort((a, b) => b[0].length - a[0].length);
    for (const [abbr, name] of prefixes) {
      if (!wanted.startsWith(abbr + " ")) continue;
      // "BA/BS" names two degrees.
      if (wanted.slice(abbr.length).split(" ").some(word => prefixes.some(([a]) => a === word))) return null;
      return [name.split(" ")[0], name];
    }
    if (DEGREE_LEVELS[wanted]) return [DEGREE_LEVELS[wanted], ""];
    return null;
  }
  function degreeOf(text) {
    const decorated = /^(.*?)\s*\(([^()]+)\)\s*$/.exec(String(text || "").trim());
    const found = (decorated ? [decorated[1], decorated[2]] : [text]).map(degreePart).filter(Boolean);
    return found.find(d => d[1]) || found[0] || null;
  }
  /** Options naming the wanted degree, else (for a named degree) the bare level. */
  function degreeMatches(options, value) {
    const wanted = degreeOf(value);
    if (!wanted) return [];
    const parsed = options.map(o => [o, degreeOf(o.text) || degreeOf(o.value)]);
    const same = parsed.filter(([, d]) => d && d[0] === wanted[0] && d[1] === wanted[1]).map(([o]) => o);
    if (same.length || !wanted[1]) return same;
    return parsed.filter(([, d]) => d && d[0] === wanted[0] && !d[1]).map(([o]) => o);
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
      if (!matches.length && eeo[key]) {
        const rule = new RegExp(eeo[key]);
        matches = options.filter(o => rule.test(norm(o.text)));
      }
      if (!matches.length && key === "degree_level") matches = degreeMatches(options, value);
    }
    if (matches.length !== 1) {
      // No "LinkedIn" in the source list: "Other", and the source goes into the
      // "please specify" field the choice usually reveals.
      if (key === "how_heard" && target !== "other") {
        const chosen = selectByText(selectEl, "Other", "how_heard_other");
        if (chosen) revealed = true;
        return chosen;
      }
      return null;
    }
    const opt = matches[0];
    selectEl.value = opt.value;
    selectEl.dispatchEvent(new Event("input", { bubbles: true }));
    selectEl.dispatchEvent(new Event("change", { bubbles: true }));
    return selectEl.value === opt.value ? opt.text.trim() : null;
  }

  /** Tick a checkbox; a styled one takes the click on its label. */
  function tick(input) {
    if (input.checked) return true;
    input.click();
    if (!input.checked && input.id) document.querySelector(`label[for="${CSS.escape(input.id)}"]`)?.click();
    return input.checked;
  }

  /**
   * Click a radio/checkbox whose label matches the desired value. Returns true when
   * answered, false when not, and "skip" for a self-identification checkbox that is some
   * other answer's option (its sibling carries the answer).
   */
  function fillChoiceGroup(el, value, label, key) {
    const val = norm(value);
    const name = el.name;
    const rule = eeo[key] ? new RegExp(eeo[key]) : null;
    const single = el.type === "checkbox" &&
      (!name || document.querySelectorAll(`input[type="checkbox"][name="${CSS.escape(name)}"]`).length === 1);
    if (rule && el.type === "checkbox" && single) {
      // Workday's disability form: one unnamed checkbox per answer ("No, I do not have a
      // disability..."), not a yes/no switch.
      const text = norm(optionText(el) || labelFor(el));
      if (!rule.test(text)) return "skip";
      if (tick(el)) revealed = true;
      return el.checked;
    }
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
    const texts = Array.from(group, input => norm(optionText(input) || labelFor(input)));
    for (const [index, input] of Array.from(group).entries()) {
      const candidates = [texts[index], norm(input.value)];
      if (candidates.includes(val) || (val === "yes" && candidates.includes("1")) || (val === "no" && candidates.includes("0"))) {
        // A group's checkbox is an option like a radio: the matching one is ticked.
        if (el.type === "checkbox") return tick(input);
        if (!input.checked) input.click();
        return true;
      }
    }
    if (rule) {
      const hits = Array.from(group).filter((_input, index) => rule.test(texts[index]));
      if (hits.length === 1) {
        if (el.type === "checkbox") return tick(hits[0]);
        if (!hits[0].checked) hits[0].click();
        return hits[0].checked;
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

  /** The hint key a control matches by selector (quote style never matters here). */
  function hintKeyFor(el) {
    for (const [hintSel, key] of Object.entries(hints || {})) {
      if (hintSel === "confirmation_text" || hintSel === "submit") continue;
      try {
        if (el.matches(hintSel)) return key;
      } catch (_) {
        /* invalid selector — skip */
      }
    }
    return "";
  }

  for (const fileEl of document.querySelectorAll('input[type="file"]')) {
    const fileSel = selectorFor(fileEl);
    const section = sectionHeading(fileEl);
    const fileLbl = labelFor(fileEl) || section;
    if (!file_inputs.some((f) => f.selector === fileSel)) {
      // Workday labels its resume input "Upload a file (5MB max)"; the hint and the
      // "Resume/CV" heading say what it is for.
      file_inputs.push({ selector: fileSel, label: fileLbl, section, hint_key: hintKeyFor(fileEl) });
    }
  }

  /** Date inputs split into year and month boxes (educations[0].start_date.year). */
  function datePart(el, label) {
    const name = el.getAttribute("name") || "";
    const placeholder = el.getAttribute("placeholder") || "";
    if (/\.year$/i.test(name) || /^yyyy$/i.test(placeholder) || /\(year\)/i.test(label)) return "year";
    if (/\.month$/i.test(name) || /^mm$/i.test(placeholder) || /\(month\)/i.test(label)) return "month";
    return "";
  }

  const controls = Array.from(
    document.querySelectorAll("input, select, textarea")
  ).filter(isVisible);

  // The previous control's key, in document order: "If other, please specify" right
  // after "How did you hear" is the source detail.
  let previousKey = null;
  for (const el of controls) {
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    const label = labelFor(el);
    const sel = selectorFor(el);
    const required = el.required || el.getAttribute("aria-required") === "true";

    if (type === "file" || skipTypes.has(type)) continue;
    // Workday: a honeypot "for robots only" input, and the search box of a multiselect
    // prompt (typing there does not commit a choice; the fill runner owns those).
    if (el.getAttribute("data-automation-id") === "beecatcher") continue;
    // The options of an open prompt popup (Skills search results) are not questions.
    if (el.closest("[data-automation-id='promptOption'], [data-automation-id='promptLeafNode'], [data-automation-id='activeListContainer'], [role='listbox']")) continue;
    if (el.closest("[data-automation-id='multiselectInputContainer']")) {
      previousKey = matchKey(el, label);
      continue;
    }
    let key = matchKey(el, label);
    if ((!key || key === "how_heard") && previousKey === "how_heard" && el.tagName !== "SELECT" &&
        !["radio", "checkbox"].includes(type) && /specify|if other|please explain/i.test(label)) {
      key = "how_heard_detail";
    }
    previousKey = key;
    if (el.getAttribute("role") === "combobox" || isReactSelect(el)) {
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
    if (existingAnswer && key === "preferred_name" && fields.preferred_name && fields.first_name &&
        norm(existingAnswer) === norm(fields.first_name) && norm(fields.preferred_name) !== norm(fields.first_name)) {
      setNativeValue(el, fields.preferred_name);
      el.blur();
      if (norm(el.value) === norm(fields.preferred_name)) {
        filled.push({ key, label, value: el.value, selector: sel, corrected: true });
      } else {
        leftovers.push({ key, label, type, required, selector: sel, reason: "Preferred name correction did not commit" });
      }
      continue;
    }
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

    if (el.tagName === "TEXTAREA" && key !== "how_heard_detail") {
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
      // A recognised question whose profile fact is blank: the fill result names the
      // profile field to set (`packet.missing_profile`).
      leftovers.push({
        key,
        label,
        type,
        options:
          el.tagName === "SELECT"
            ? Array.from(el.options).map((o) => o.text.trim())
            : [],
        required,
        selector: sel,
        reason: "Profile field is blank",
      });
      if (required) required_empty.push(label || sel);
      continue;
    }

    let written = "";
    if (el.tagName === "SELECT") {
      const yearOnly = (key === "education_start_month" || key === "graduation_month") &&
        /(?:start|end|graduation|attended).{0,12}year|year.{0,12}(?:start|end|graduation)|(?:first|last) year attended/i.test(`${el.id} ${label}`);
      // The named degree ("Bachelor of Science") also answers a "BS"/"BA" list.
      if (key === "degree_level" && fields.degree_name) written = selectByText(el, fields.degree_name, key) || "";
      if (!written) written = selectByText(el, yearOnly ? String(value).slice(0, 4) : value, key) || "";
      if (!written) {
        leftovers.push({ label, type, options: Array.from(el.options).map((o) => o.text.trim()), required, selector: sel, reason: "No unique matching option" });
        if (required) required_empty.push(label || sel);
        continue;
      }
    } else if (type === "radio" || type === "checkbox") {
      const chosen = fillChoiceGroup(el, value, label, key);
      if (chosen === "skip") continue;
      if (!chosen) {
        leftovers.push({ label, type, options: [], required, selector: sel, reason: "No exact matching choice" });
        if (required) required_empty.push(label || sel);
        continue;
      }
      written = String(value);
    } else if (value === "decline" && eeo[key]) {
      // Declining picks a choice; it is never typed into a text box.
      leftovers.push({ key, label, type, options: [], required, selector: sel, reason: "Declined to self-identify" });
      if (required) required_empty.push(label || sel);
      continue;
    } else {
      let textValue = String(value);
      if (key === "graduation_month" && /end[-_ ]?year/i.test(el.id || label)) textValue = textValue.slice(0, 4);
      if (key === "education_start_month" && /start[-_ ]?year/i.test(el.id || label)) textValue = textValue.slice(0, 4);
      if (key === "education_start_month" || key === "graduation_month") {
        const part = datePart(el, label);
        const date = /^(\d{4})(?:-(\d{2}))?/.exec(String(value));
        if (part && date) {
          if (part === "year") textValue = date[1];
          else if (date[2]) textValue = String(Number(date[2]));
          else {
            leftovers.push({ key, label, type, options: [], required, selector: sel, reason: "No month in the profile date" });
            if (required) required_empty.push(label || sel);
            continue;
          }
        }
      }
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
