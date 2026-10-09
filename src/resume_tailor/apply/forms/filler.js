/**
 * Deterministic ATS form filler — injected via Playwright page.evaluate.
 * Receives { fields, hints, synonyms, eeo } and returns fill diagnostics; ``eeo`` maps
 * a self-identification key to the regexes (over ``norm``ed option text) that pick its
 * answer, most specific first (`field_matcher.eeo_patterns`: the first regex naming
 * exactly one option wins, one naming two stops). ``correct`` runs only the post-upload pass: put
 * back contact facts an ATS's resume parser overwrote, and touch nothing else.
 *
 * ``scan`` fills nothing and returns ``{ questions }``: one entry per question (a radio,
 * checkbox or toggle-button group counts once) with its id, label, kind, options and
 * date part. `questions.plan_for` turns those into ``plan``, ``{ qid: { key, value } }``;
 * given a plan, a planned question takes its key from it (null: leave it for review)
 * and its ``value``, when set, over ``fields[key]`` (`fill._fill_frame`).
 */
({ fields, hints, synonyms, eeo = {}, educationAliases = {}, correct = false, scan = false, plan = null }) => {
  const filled = [];
  const leftovers = [];
  const long_text = [];
  const file_inputs = [];
  const required_empty = [];
  // Set when a tick may have revealed more fields; the fill runner then scans again.
  let revealed = false;

  /**
   * Index into ``texts`` (``norm``ed option texts) of the one option ``eeo[key]`` names:
   * each tier in turn, the first naming exactly one wins; -1 when none names one, -2 when
   * a tier names two (ambiguous: left for review, never guessed).
   */
  function eeoPick(texts, key) {
    for (const pattern of [].concat(eeo[key] || [])) {
      const rule = new RegExp(pattern);
      const hits = [];
      texts.forEach((text, index) => { if (rule.test(text)) hits.push(index); });
      if (hits.length === 1) return hits[0];
      if (hits.length > 1) return -2;
    }
    return -1;
  }

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

  /** The document or shadow root holding el: its `label[for]` and radio group live there. */
  function rootOf(el) {
    const root = el.getRootNode();
    return root && typeof root.querySelectorAll === "function" ? root : document;
  }

  /**
   * querySelectorAll that also searches open shadow roots, in document order. Web-component
   * forms (SmartRecruiters' apply page) keep their inputs there; closed roots stay hidden,
   * as they are from the page's own scripts. Playwright's CSS locators pierce open roots,
   * so the selectors reported back still resolve.
   */
  function deepQueryAll(root, sel) {
    const out = [];
    for (const node of root.querySelectorAll("*")) {
      if (node.matches(sel)) out.push(node);
      if (node.shadowRoot) out.push(...deepQueryAll(node.shadowRoot, sel));
    }
    return out;
  }

  /**
   * A CSS selector for el. A radio/checkbox group member is named by its group (the
   * group is the question); anything else gets a path grown until it matches el alone:
   * a short ``div:nth-of-type`` path can match another control, whose value is then read
   * back as this one's (Ramp's Phone "filled" with the School typeahead's text).
   */
  function selectorFor(el) {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const name = el.getAttribute("name");
    const tag = el.tagName.toLowerCase();
    const root = rootOf(el);
    const unique = (sel) => {
      try {
        return root.querySelectorAll(sel).length === 1;
      } catch (_) {
        return false;
      }
    };
    if (name) {
      const byName = `${tag}[name="${name.replace(/"/g, '\\"')}"]`;
      if (el.type === "radio" || el.type === "checkbox" || unique(byName)) return byName;
    }
    const automationId = el.getAttribute("data-automation-id");
    if (automationId && document.querySelectorAll(`[data-automation-id="${CSS.escape(automationId)}"]`).length === 1) {
      return `${el.tagName.toLowerCase()}[data-automation-id="${automationId.replace(/"/g, '\\"')}"]`;
    }
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && (parts.length < 4 || !unique(parts.join(" > ")))) {
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
  /**
   * Lever custom questions: ``cards[<card>][field<N>]`` controls. The card's hidden
   * ``cards[<card>][baseTemplate]`` JSON names each field's exact question and whether it
   * is required, which the markup marks only with a styled "✱".
   */
  const leverCards = new Map();
  function leverQuestion(el) {
    const match = /^cards\[([^\]]+)\]\[field(\d+)\]/.exec(el.getAttribute("name") || "");
    if (!match) return null;
    if (!leverCards.has(match[1])) {
      let card = null;
      const template = rootOf(el).querySelector(`input[name="cards[${CSS.escape(match[1])}][baseTemplate]"]`);
      try {
        card = JSON.parse(template?.value || "null");
      } catch {
        card = null;
      }
      leverCards.set(match[1], card);
    }
    const field = leverCards.get(match[1])?.fields?.[Number(match[2])];
    const text = field && typeof field.text === "string" ? field.text.trim() : "";
    return text ? { text, required: field.required === true } : null;
  }

  /** A radio/checkbox with siblings of its name: one option of a question. */
  const CONTROLS = "input:not([type='hidden']), select, textarea";
  const textOf = (node) => (node?.innerText || node?.textContent || "").replace(/[⁠​]/g, "").replace(/\s+/g, " ").trim();

  /** Toggle buttons answering one question (Ashby's Yes/No): el's own, or el's siblings. */
  function toggleButtons(el) {
    const parent = el.tagName === "BUTTON" ? el.parentElement : el.parentElement;
    const buttons = parent ? Array.from(parent.querySelectorAll(":scope > button[aria-pressed]")) : [];
    return buttons.length > 1 ? buttons : [];
  }

  /**
   * The options answering the same question as el: radios/checkboxes sharing its name;
   * else checkboxes each named after themselves inside one fieldset or group (Ashby's
   * race list); else a toggle-button group, whose decoy checkbox rides along.
   */
  function questionMembers(el) {
    const buttons = toggleButtons(el);
    if (buttons.length) {
      const decoys = Array.from(buttons[0].parentElement.querySelectorAll(":scope > input"));
      return [...buttons, ...decoys];
    }
    if (el.type !== "radio" && el.type !== "checkbox") return [el];
    const root = rootOf(el);
    if (el.name) {
      const named = Array.from(root.querySelectorAll(`input[type="${el.type}"][name="${CSS.escape(el.name)}"]`));
      if (named.length > 1) return named;
    }
    const box = el.closest("fieldset, [role='group'], [role='radiogroup']");
    if (box) {
      const all = Array.from(box.querySelectorAll(CONTROLS));
      if (all.length > 1 && all.every((other) => other.type === el.type)) return all;
    }
    return [el];
  }

  /** The options (not the decoy) of el's question. */
  function questionOptions(el) {
    return questionMembers(el).filter((member) => member.tagName === "BUTTON" || member.type === "radio" || member.type === "checkbox")
      .filter((member, _i, all) => member.tagName === "BUTTON" || !all.some((other) => other.tagName === "BUTTON"));
  }

  function isGroupMember(el) {
    return questionMembers(el).length > 1;
  }

  /** One id for a question: its group's name or container, else the control's selector. */
  function questionId(el) {
    const members = questionMembers(el);
    if (members.length < 2) return selectorFor(el);
    const first = members[0];
    if (first.tagName !== "BUTTON" && first.name && members.every((member) => member.name === first.name)) {
      return selectorFor(first);
    }
    return `group:${selectorFor(first)}`;
  }

  /**
   * A wrapper's own label: ``<label for="startDate">`` naming the element that holds the
   * month and year selects (Ashby's date fields), not a control of its own.
   */
  function wrapperLabel(el) {
    const root = rootOf(el);
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      if (!node.id || node.matches(CONTROLS)) continue;
      const label = root.querySelector(`label[for="${CSS.escape(node.id)}"]`);
      if (label && !label.querySelector(CONTROLS)) return textOf(label);
    }
    return "";
  }

  /**
   * The label nearest before el in the smallest field holding only el: Ashby puts the
   * question in a ``<label>`` whose ``for`` names no element, then helper text ("For most
   * recent or in progress degree."), then the control — the helper is not the question.
   */
  function fieldLabel(el) {
    const root = rootOf(el);
    const members = questionMembers(el);
    const ours = (other) => members.includes(other);
    for (let node = el.parentElement, depth = 0; node && node !== document.body && depth < 8; node = node.parentElement, depth++) {
      if (Array.from(node.querySelectorAll(CONTROLS)).some((other) => !ours(other))) break;
      const labels = Array.from(node.querySelectorAll("label")).filter((label) => {
        if (label.querySelector(CONTROLS)) return false;  // an option's own wrapping label
        const target = label.getAttribute("for");
        const named = target ? root.getElementById?.(target) || document.getElementById(target) : null;
        // A label for this control or its group's options is an option, not the question.
        if (named && named.matches?.(CONTROLS)) return false;
        return Boolean(label.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      const text = textOf(labels[labels.length - 1]);
      if (text) return text.replace(/\s*\*\s*$/, "");
    }
    return "";
  }

  function labelFor(el) {
    const lever = leverQuestion(el);
    if (lever) return lever.text;
    // One option of a radio/checkbox question stands for the question.
    if (isGroupMember(el)) {
      const question = groupQuestion(el);
      if (question) return question;
    }
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
      // A space-separated id list: the question plus, often, its hint or error text.
      const text = labelledBy.split(/\s+/).map(ref => root.getElementById(ref))
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
    const wrapper = wrapperLabel(el);
    if (wrapper) return wrapper;
    const field = fieldLabel(el);
    if (field) return field;
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
      const lbl = rootOf(input).querySelector(`label[for="${CSS.escape(input.id)}"]`);
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

  /** One box for the whole international number: a ^\+ pattern, or an "international" /
   * "include country code" / "E.164" hint. A "+1 (555)" placeholder alone is not enough:
   * masked inputs show one and add the +1 themselves. */
  function wantsInternational(el, label) {
    const placeholder = el.getAttribute("placeholder") || "";
    if (/^\^?\\?\+/.test(el.getAttribute("pattern") || "")) return true;
    const described = el.getAttribute("aria-describedby");
    const help = described ? rootOf(el).getElementById?.(described)?.textContent || "" : "";
    return /international|e\.?164|include (?:the |your )?country code|with country code/i
      .test(`${placeholder} ${label || ""} ${help}`);
  }

  /** A phone prefix is a distinct field even when the widget is called country. */
  function phoneCodeControl(el, label) {
    const clues = `${label} ${el.id} ${el.name || ""} ${el.getAttribute("autocomplete") || ""}`.toLowerCase();
    // "Phone (include country code)" is the number box itself, asking for +<code>.
    if (el.getAttribute("type") === "tel" &&
        /\b(?:include|including|with)\s+(?:the\s+|your\s+)?country\s+code/.test(clues)) return false;
    if (/tel-country-code|dial(?:ling|ing)?[ _-]*code|calling[ _-]*code|phone[ _-]*country|country[ _/-]*code/.test(clues)) return true;
    if (!/country/.test(clues)) return false;
    if (el.tagName !== "SELECT" && el.getAttribute("role") !== "combobox") return false;
    if (el.id === "country" && /^phone\b/i.test(sectionHeading(el))) return true;
    const group = el.closest("fieldset, [class*='phone' i], [data-field*='phone' i], .form-group");
    const nearPhone = group && group.querySelector("input[type='tel'], input[name*='phone' i]");
    if (nearPhone && el.getAttribute("role") === "combobox" &&
        /phone/i.test(`${group.className || ""} ${group.getAttribute("data-field") || ""}`)) return true;
    const options = el.tagName === "SELECT" ? Array.from(el.options) : [];
    const codes = options.filter(o => /\+\d{1,4}\b/.test(o.textContent || ""));
    return Boolean(nearPhone && codes.length >= 2);
  }

  /** Match a field key via the DOM's own facts, then label synonyms. */
  function matchKey(el, label) {
    const degreeLabel = /\b(degree|qualification|highest.*education|education level|level of education|educational attainment)\b/i.test(label);
    const semantic = degreeLabel ? educationKey(label + " " + helpFor(el)) : null;
    if (semantic) return semantic;
    if (/highest\s+degree\s+of\s+(?!education\b)/i.test(label)) return null;
    return attrKey(el, label) || labelKey(el, label);
  }

  function educationKey(text) {
    text = text.replace(/\b(do not|don't|not|exclude|excluding)\b.{0,45}\b(pursuing|in progress|working toward)\b(?:\s+degrees?)?/gi, "");
    for (const [pattern, key] of synonymList) {
      if (["highest_education_obtained", "education_completed_or_pursuing", "completed_education_other"].includes(key)
          || (key === "degree_level" && pattern.includes("pursuing"))) {
        if (new RegExp(pattern, "i").test(text)) return key;
      }
    }
    return null;
  }

  function valueForKey(key) {
    if (key === "education_completed_or_pursuing") {
      return fields.degree_level ? fields.degree_name || fields.degree_level : fields.highest_education_obtained;
    }
    return fields[key];
  }

  /**
   * A key the DOM itself states: an ATS hint selector, an education-date input's id or
   * name, a phone-code control, Workday's preferred-name block. A plan from the fill
   * runner keeps these; label wording is the decision layer's (`questions.py`).
   */
  function attrKey(el, label) {
    if (/^end[-_ ]?(?:year|month)(?:--\d+)?$/i.test(el.id || "")) return "graduation_month";
    if (/^start[-_ ]?(?:year|month)(?:--\d+)?$/i.test(el.id || "")) return "education_start_month";
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
    return null;
  }

  /** The key autocomplete / automation-id / name attributes alone name ("given-name"). */
  function nameKey(el) {
    const name = el.getAttribute("name") || "";
    const auto = el.getAttribute("autocomplete") || el.getAttribute("data-automation-id") ||
      el.getAttribute("data-field") || "";
    const haystack = `${auto} ${name.replace(/[._\-\[\]]+/g, " ")}`.toLowerCase().trim();
    if (!haystack || /^(?:on|off)$/.test(haystack)) return null;
    for (const [pattern, key] of synonymList) {
      try {
        if (new RegExp(pattern, "i").test(haystack)) return key;
      } catch (_) {
        /* bad regex — skip */
      }
    }
    return null;
  }

  function labelKey(el, label) {
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
    if (["highest_education_obtained", "education_completed_or_pursuing"].includes(key)) {
      // Labels decide education; opaque option values cannot hide "in progress".
      matches = options.filter(o => norm(o.text) === target);
      if (!matches.length) {
        const canonical = educationAliases[target];
        if (canonical) matches = options.filter(o => {
          const parts = o.text.split(/\s+or\s+|\s*[/;]\s*/i);
          return educationAliases[norm(o.text)] === canonical ||
            (parts.length > 1 && parts.some(part => educationAliases[norm(part)] === canonical));
        });
      }
      if (!matches.length) {
        const clean = options.filter(o => !/\b(pursuing|in progress|incomplete|not completed|no degree)\b/i.test(o.text));
        const named = degreeMatches(clean.map(o => ({ text: o.text, value: "", original: o })), value);
        matches = named.map(o => o.original);
      }
    } else if (key === "phone_country_code") {
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
        const index = eeoPick(options.map(o => norm(o.text)), key);
        matches = index >= 0 ? [options[index]] : index === -2 ? options : [];
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

  /**
   * Answer a question whose options are toggle buttons or checkboxes named after
   * themselves: the option saying ``value`` (exactly, a "Yes"/"No" head, or a
   * self-identification answer's option), verified. Returns its text, or null.
   */
  /** The option of a group that says value, set; null when none does or it would not stick. */
  function fillGroup(options, value, key) {
    const texts = options.map((option) => norm(option.tagName === "BUTTON" ? textOf(option) : optionText(option)));
    const wanted = norm(value);
    let index = texts.indexOf(wanted);
    if (["highest_education_obtained", "education_completed_or_pursuing"].includes(key)
        && texts.filter(text => text === wanted).length > 1) return null;
    if (index < 0 && (wanted === "yes" || wanted === "no")) {
      const heads = texts.flatMap((text, i) => (text.split(" ")[0] === wanted ? [i] : []));
      if (heads.length === 1) index = heads[0];
    }
    if (index < 0 && eeo[key]) index = eeoPick(texts, key);
    if (index < 0) return null;
    const option = options[index];
    if (option.tagName === "BUTTON") {
      if (option.getAttribute("aria-pressed") !== "true") option.click();
      return option.getAttribute("aria-pressed") === "true" ? option : null;
    }
    if (option.type === "checkbox") return tick(option) ? option : null;
    if (!option.checked) option.click();
    return option.checked ? option : null;
  }

  const MONTH_NAME = /^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?$/i;
  const DATE_HINT = /\b(?:pick|select|choose|enter) (?:a )?date\b|^(?:mm|dd|yyyy)\s*[/.-]/i;

  /** "month"/"year" for one box of a split date: its name, placeholder, first option or options. */
  function datePartOf(el, label, options) {
    const stated = datePart(el, label);
    if (stated) return stated;
    const first = el.tagName === "SELECT" ? (el.options[0]?.text || "").trim() : "";
    const real = options.filter((option) => option && !/^(select|choose|please select|month|year)\b/i.test(option));
    if (/^month\b/i.test(first) || (real.length >= 12 && real.filter((option) => MONTH_NAME.test(option.trim())).length >= 12)) return "month";
    if (/^year\b/i.test(first) || (real.length >= 3 && real.every((option) => /^\d{4}$/.test(option.trim())))) return "year";
    if (el.tagName === "SELECT" || el.type === "number") {
      if (/\bmonth\b/i.test(label) && !/\byear\b/i.test(label)) return "month";
      if (/\byear\b/i.test(label) && !/\bmonth\b/i.test(label)) return "year";
    }
    return "";
  }

  /** Helper text shown with a question ("For most recent or in progress degree."). */
  function helpFor(el) {
    const described = el.getAttribute("aria-describedby");
    if (described) {
      const text = described.split(/\s+/).map((ref) => rootOf(el).getElementById?.(ref)).filter(Boolean).map(textOf).join(" ");
      if (text) return text.slice(0, 300);
    }
    const field = el.closest("[class*='field-entry' i], [class*='form-group' i], fieldset");
    return textOf(field?.querySelector("[class*='description' i], [class*='help-text' i], [class*='hint' i]")).slice(0, 300);
  }

  /** One question for the fill runner's plan (`questions.py`): what it asks and how. */
  function describe(el, { qid, members, buttonGroup, label, sel, required }) {
    const type = (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    const options = members.length > 1
      ? questionOptions(el).map((option) => (option.tagName === "BUTTON" ? textOf(option) : optionText(option)))
      : el.tagName === "SELECT" ? Array.from(el.options).map((option) => option.text.trim()) : [];
    const combo = el.getAttribute("role") === "combobox" || isReactSelect(el);
    const kind = buttonGroup || type === "radio" || el.tagName === "SELECT" ? "choice"
      : type === "checkbox" ? (members.length > 1 ? "multi" : "checkbox")
      : combo ? "typeahead"
      : el.tagName === "TEXTAREA" ? "textarea"
      : type === "date" || DATE_HINT.test(el.getAttribute("placeholder") || "") ? "date"
      : "text";
    return {
      qid, selector: sel, label, help: helpFor(el), kind, options, required,
      part: kind === "choice" || kind === "text" || kind === "typeahead" ? datePartOf(el, label, options) : "",
      attr_key: attrKey(el, label) || "", name_key: nameKey(el) || "",
      placeholder: el.getAttribute("placeholder") || "", input_type: type,
      section: sectionHeading(el),
    };
  }

  /** Tick a checkbox; a styled one takes the click on its label. */
  function tick(input) {
    if (input.checked) return true;
    input.click();
    if (!input.checked && input.id) rootOf(input).querySelector(`label[for="${CSS.escape(input.id)}"]`)?.click();
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
    const rule = !!eeo[key];
    const root = rootOf(el);
    const single = el.type === "checkbox" &&
      (!name || root.querySelectorAll(`input[type="checkbox"][name="${CSS.escape(name)}"]`).length === 1);
    if (rule && el.type === "checkbox" && single) {
      // Workday's disability form: one unnamed checkbox per answer ("No, I do not have a
      // disability..."), not a yes/no switch. The answer is chosen among the question's
      // boxes, so a fallback tier never ticks a second box beside the first tier's.
      const container = el.closest("fieldset, [role='group'], [data-automation-id^='formField-']");
      const boxes = container
        ? Array.from(container.querySelectorAll('input[type="checkbox"]'))
        : [el];
      const index = eeoPick(boxes.map(box => norm(optionText(box) || labelFor(box))), key);
      if (index < 0 || boxes[index] !== el) return "skip";
      if (tick(el)) revealed = true;
      return el.checked;
    }
    if (single) {
      // A lone checkbox is a yes/no switch ("I have a preferred name").
      if (!["yes", "true", "1", "no", "false", "0"].includes(val)) return false;
      const shouldCheck = ["yes", "true", "1"].includes(val);
      if (el.checked !== shouldCheck) {
        el.click();
        if (el.checked !== shouldCheck && el.id) root.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.click();
        if (shouldCheck) revealed = true;
      }
      return el.checked === shouldCheck;
    }
    if (!name) return false;
    const group = root.querySelectorAll(
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
      const index = eeoPick(texts, key);
      if (index >= 0) {
        const hit = group[index];
        if (el.type === "checkbox") return tick(hit);
        if (!hit.checked) hit.click();
        return hit.checked;
      }
    }
    return false;
  }

  /**
   * "Which offices are you interested in? (select all)": a checkbox list of places. Named
   * groups of two or more under a location question only; a lone checkbox is a switch.
   */
  const LOCATION_QUESTION = /\b(?:locations?|offices?|cities|sites?|hubs?)\b|\bwhere\b.{0,40}\bwork\b/i;
  function locationGroup(el) {
    if (el.type !== "checkbox" || !el.name) return null;
    const group = Array.from(
      rootOf(el).querySelectorAll(`input[type="checkbox"][name="${CSS.escape(el.name)}"]`)
    );
    if (group.length < 2) return null;
    const question = groupQuestion(el);
    return LOCATION_QUESTION.test(question) ? { group, question } : null;
  }

  /** A checkbox group's question: its legend or group label, not one option's label. */
  function groupQuestion(el) {
    if (el.getAttribute("description")) return el.getAttribute("description");
    const described = (el.getAttribute("aria-describedby") || "").split(/\s+/)
      .map(id => rootOf(el).getElementById?.(id)).find(node => node && !/error/i.test(node.id));
    if (described && textOf(described)) return textOf(described);
    const lever = leverQuestion(el);
    if (lever) return lever.text;
    const fieldset = el.closest("fieldset");
    const legend = fieldset?.querySelector("legend");
    if (legend) return (legend.innerText || legend.textContent || "").trim();
    const labelled = el.closest("[role='group'][aria-labelledby], [role='radiogroup'][aria-labelledby]")
      ?.getAttribute("aria-labelledby");
    const byId = labelled ? rootOf(el).getElementById(labelled.split(/\s+/)[0]) : null;
    if (byId) return (byId.innerText || byId.textContent || "").trim();
    // Ashby: the fieldset's own <label>, before its helper text and options.
    return fieldLabel(el) || containerLabel(el);
  }

  /** A place's name without its region: "New York, NY" and "London (Hybrid)" -> head. */
  function placeHead(text) {
    return norm(String(text || "").split(/,|\(| - | – /)[0]);
  }

  /**
   * Tick every option the profile's location preference names, else the posting's own
   * location. ``{ picked, guessed }``: with neither matching, a required list gets its
   * first option and ``guessed`` so the applicant checks it; an optional one stays blank.
   */
  function fillLocations(group, required) {
    const texts = group.map(input => optionText(input) || labelFor(input));
    const wanted = (source) => {
      const haystack = ` ${norm(source)} `;
      if (!haystack.trim()) return [];
      return group.filter((_input, index) => {
        const head = placeHead(texts[index]);
        return head.length >= 3 && haystack.includes(` ${head} `);
      });
    };
    let hits = wanted(fields.location_preference);
    if (!hits.length) hits = wanted(fields.posting_location);
    let guessed = false;
    if (!hits.length && required) {
      hits = [group[0]];
      guessed = true;
    }
    const picked = [];
    for (const input of hits) {
      if (tick(input)) picked.push(texts[group.indexOf(input)]);
    }
    return { picked, guessed };
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

  for (const fileEl of deepQueryAll(document, 'input[type="file"]')) {
    const fileSel = selectorFor(fileEl);
    const section = sectionHeading(fileEl);
    const fileLbl = textOf(fileEl.closest('.file-upload')?.querySelector('.upload-label, .file-upload__label')) || labelFor(fileEl) || section;
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
    // Greenhouse's education dates: ids start-month--0 / end-year--0.
    const id = el.id || "";
    if (/\.year$/i.test(name) || /[-_]year(?:--\d+)?$/i.test(id) || /^yyyy$/i.test(placeholder) || /\(year\)/i.test(label)) return "year";
    if (/\.month$/i.test(name) || /[-_]month(?:--\d+)?$/i.test(id) || /^mm$/i.test(placeholder) || /\(month\)/i.test(label)) return "month";
    return "";
  }

  /** The phone in the shape this box wants: national beside a code control, else E.164 when asked. */
  function phoneText(el, label, typed) {
    const workdayPhoneCode = document.querySelector("[data-automation-id='formField-countryPhoneCode']");
    if (fields.phone_country_code && (workdayPhoneCode ||
        (el.getAttribute("type") === "tel" &&
         deepQueryAll(document, "select,[role='combobox']").some(other => phoneCodeControl(other, labelFor(other)))))) {
      // A separate country-code control: type only the national number.
      const code = String(fields.phone_country_code);
      if (fields.phone_national) return String(fields.phone_national);
      return typed.startsWith(code) ? typed.slice(code.length).replace(/^[\s()\-.]+/, "") : typed;
    }
    if (fields.phone_e164 && wantsInternational(el, label)) return String(fields.phone_e164);
    return typed;
  }

  /**
   * Contact facts a resume parser fills (Greenhouse, Workday, iCIMS read the uploaded PDF).
   * The profile is the source of truth for these; anything else the ATS wrote is kept.
   */
  const CORRECTABLE_KEYS = new Set([
    "first_name", "last_name", "email", "phone", "address_line1", "city", "postal_code",
    "linkedin_url", "github_url", "portfolio_url", "website", "school", "major", "gpa",
  ]);

  /** Whether a pre-filled value says the same thing as the profile, formatting aside. */
  function agrees(key, current, wanted) {
    if (key === "phone") {
      const a = current.replace(/\D/g, "");
      const b = wanted.replace(/\D/g, "");
      return Boolean(a && b) && (a.endsWith(b) || b.endsWith(a));
    }
    if (key.endsWith("_url") || key === "website") {
      const bare = (url) => url.toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/+$/, "");
      return bare(current) === bare(wanted);
    }
    return norm(current) === norm(wanted);
  }

  // Toggle-button groups (Ashby's Yes/No) are questions too; a group is visited once.
  const controls = deepQueryAll(document, "input, select, textarea, button[aria-pressed]").filter(isVisible);
  const questions_out = [];

  // The previous control's key, in document order: "If other, please specify" right
  // after "How did you hear" is the source detail.
  let previousKey = null;
  // Location checkbox lists already answered as a whole (by group name).
  const locationNames = new Set();
  // Questions already answered or reported: a group is one question, not one per option.
  const doneQuestions = new Set();
  for (const el of controls) {
    const members = questionMembers(el);
    const buttonGroup = members[0]?.tagName === "BUTTON";
    // A toggle-button group is handled at its first button; its decoy input with it.
    if (buttonGroup && el !== members[0]) continue;
    const type = buttonGroup ? "buttons"
      : (el.getAttribute("type") || el.tagName.toLowerCase()).toLowerCase();
    if (type === "file" || skipTypes.has(type)) continue;
    // Workday: a honeypot "for robots only" input, and the search box of a multiselect
    // prompt (typing there does not commit a choice; the fill runner owns those).
    if (el.getAttribute("data-automation-id") === "beecatcher") continue;
    if (el.closest('.select__control, [class*="-control"]') && el.getAttribute('role') !== 'combobox' && !isReactSelect(el)) continue;
    // The options of an open prompt popup (Skills search results) are not questions.
    if (el.closest("[data-automation-id='promptOption'], [data-automation-id='promptLeafNode'], [data-automation-id='activeListContainer'], [role='listbox']")) continue;
    if (el.closest("[data-automation-id='multiselectInputContainer']")) {
      if (!scan) previousKey = matchKey(el, labelFor(el));
      continue;
    }
    const qid = questionId(el);
    const multiMember = members.length > 1 && (buttonGroup || !el.name || members.some((member) => member.name !== el.name));
    if (multiMember && doneQuestions.has(qid)) continue;
    const label = labelFor(el);
    const sel = selectorFor(el);
    const required = el.required || el.getAttribute("aria-required") === "true" ||
      Boolean(leverQuestion(el)?.required) || members.some((member) => member.required);
    const planned = plan && Object.prototype.hasOwnProperty.call(plan, qid) ? plan[qid] : null;

    if (scan) {
      if (!doneQuestions.has(qid)) {
        doneQuestions.add(qid);
        questions_out.push(describe(el, { qid, members, buttonGroup, label, sel, required }));
      }
      continue;
    }
    if (!plan && members.length > 1 && members.every(member => member.type === 'checkbox')) {
      if (doneQuestions.has(qid)) continue;
      const selected = members.filter(member => member.checked).map(optionText);
      if (selected.length) {
        doneQuestions.add(qid);
        filled.push({key: 'existing', label, value: selected.join('; '), selector: sel, preserved: true});
        continue;
      }
    }
    if (planned && Array.isArray(planned.values)) {
      if (doneQuestions.has(qid)) continue;
      doneQuestions.add(qid);
      const options = questionOptions(el);
      const existing = options.filter(option => option.checked);
      const wanted = existing.length ? existing.map(optionText) : planned.values;
      if (!existing.length) {
        for (const option of options) {
          if (wanted.includes(optionText(option))) tick(option);
        }
      }
      const selected = options.filter(option => option.checked).map(optionText);
      if (selected.length && selected.length === wanted.length && wanted.every(value => selected.includes(value))) {
        filled.push({key: planned.key, label, value: selected.join('; '), selector: sel, preserved: existing.length > 0});
      } else {
        leftovers.push({key: planned.key, label, type: 'checkboxgroup', options: options.map(optionText), required, selector: sel, reason: 'No supported skill selection committed'});
        if (required) required_empty.push(label || qid);
      }
      continue;
    }
    if (multiMember) {
      // Options named after themselves (Ashby's race list) or toggle buttons: the group
      // is answered here as a whole.
      doneQuestions.add(qid);
      const options = questionOptions(el);
      const key = planned ? planned.key : matchKey(el, label);
      const answered = options.find((option) => option.tagName === "BUTTON"
        ? option.getAttribute("aria-pressed") === "true" : option.checked);
      if (answered) {
        filled.push({ key: "existing", label, value: answered.tagName === "BUTTON" ? textOf(answered) : optionText(answered), selector: selectorFor(answered), preserved: true });
        continue;
      }
      const value = planned && planned.value === null ? "" : planned && planned.value ? planned.value : (key ? valueForKey(key) : "");
      const texts = options.map((option) => option.tagName === "BUTTON" ? textOf(option) : optionText(option));
      if (!key || !value) {
        leftovers.push({ key, label, type, options: texts, required, selector: sel,
          reason: planned && planned.value === null ? "No unique matching option" : key ? "Profile field is blank" : "Unrecognized field" });
        if (required) required_empty.push(label || qid);
        continue;
      }
      const chosen = fillGroup(options, String(value), key);
      if (!chosen) {
        leftovers.push({ key, label, type, options: texts, required, selector: sel,
          reason: options.some((option) => norm(option.tagName === "BUTTON" ? textOf(option) : optionText(option)) === norm(value))
            ? "The choice did not stay selected" : "No exact matching choice" });
        if (required) required_empty.push(label || qid);
        continue;
      }
      filled.push({ key, label, value: chosen.tagName === "BUTTON" ? textOf(chosen) : optionText(chosen), selector: selectorFor(chosen) });
      continue;
    }
    let key = planned ? planned.key : matchKey(el, label);
    if ((!key || key === "how_heard") && previousKey === "how_heard" && el.tagName !== "SELECT" &&
        !["radio", "checkbox"].includes(type) && /specify|if other|please explain/i.test(label)) {
      key = "how_heard_detail";
    }
    previousKey = key;
    if (correct) {
      const plainText = el.tagName === "INPUT" && !["checkbox", "radio", "hidden"].includes(type) &&
        el.getAttribute("role") !== "combobox" && !isReactSelect(el);
      const current = plainText ? String(el.value || "").trim() : "";
      const wanted = key && CORRECTABLE_KEYS.has(key) ? String(fields[key] ?? "").trim() : "";
      if (!current || !wanted || agrees(key, current, wanted)) continue;
      const textValue = key === "phone" ? phoneText(el, label, wanted) : wanted;
      setNativeValue(el, textValue);
      el.blur();
      if (agrees(key, String(el.value || ""), textValue)) {
        filled.push({ key, label, value: el.value, selector: sel, corrected: true, previous: current });
      } else {
        leftovers.push({ key, label, type, required, selector: sel, reason: "The ATS changed this after the resume upload and the correction did not stick" });
      }
      continue;
    }
    if (el.getAttribute("role") === "combobox" || isReactSelect(el)) {
      const control = el.closest(".select__control, [class*='-control']");
      const selectedText = (control?.querySelector(".select__single-value, [class*='-singleValue']")?.textContent ||
        Array.from(control?.querySelectorAll('.select__multi-value__label, [class*="-multiValue"]') || []).map(textOf).join('; ')).trim();
      if (selectedText) {
        filled.push({ key: "existing", label, value: selectedText, selector: sel, preserved: true });
        continue;
      }
      leftovers.push({ key, label, type: "combobox", options: [], required, selector: sel, value: planned && planned.value ? planned.value : undefined, reason: "Custom dropdown needs an observed selection" });
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
    // Date-part text boxes can retain a fragment from an earlier fill ("14" before the
    // year: MPC's "142027"). Text that is not a well-formed year (or month) is replaced
    // with the planned part; a well-formed one is the applicant's own answer and is kept.
    const plannedPart = planned && planned.value ? String(planned.value) : "";
    const wellFormedPart = /^\d{4}$/.test(plannedPart)
      ? /^\d{4}$/.test(existingAnswer)
      : /^(?:0?[1-9]|1[0-2]|[a-z]{3,9})$/i.test(existingAnswer);
    const replaceDatePart = el.tagName === "INPUT" && type === "text" && plannedPart &&
      ["earliest_start", "graduation_month", "education_start_month"].includes(key) &&
      existingAnswer !== plannedPart && !wellFormedPart;
    // Ashby's education month/year selects arrive set to today ("September" / "2026"),
    // which read as an answer. Education dates come only from the master resume, so a
    // select that disagrees with the planned option is overwritten (Ramp, 2026-09).
    const replaceDateSelect = el.tagName === "SELECT" && plannedPart &&
      ["graduation_month", "education_start_month"].includes(key) &&
      norm(existingAnswer) !== norm(plannedPart);
    if (existingAnswer && !replaceDatePart && !replaceDateSelect) {
      filled.push({ key: "existing", label, value: existingAnswer, selector: sel, preserved: true });
      continue;
    }
    if (type === "checkbox" && locationNames.has(el.name)) continue;
    if ((type === "checkbox" || type === "radio") && el.name && Array.from(rootOf(el).querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)).some(input => input.checked)) {
      filled.push({ key: "existing", label, value: "selected", selector: sel, preserved: true });
      continue;
    }

    const places = locationGroup(el);
    if (places) {
      if (locationNames.has(el.name)) continue;
      locationNames.add(el.name);
      const question = places.question;
      const groupRequired = required || places.group.some(input => input.required);
      const { picked, guessed } = fillLocations(places.group, groupRequired);
      if (!picked.length) {
        leftovers.push({ key: "location_preference", label: question, type, options: places.group.map(input => optionText(input)), required: groupRequired, selector: sel, reason: "No listed location matches your location preference" });
        if (groupRequired) required_empty.push(question || sel);
        continue;
      }
      filled.push({ key: "location_preference", label: question, value: picked.join("; "), selector: sel });
      // Filled, but a guess: fill.py lists it for review under its own note.
      if (guessed) leftovers.push({ key: "location_preference", label: question, type, options: [], required: groupRequired, selector: sel, reason: "Picked the first location; check it", review: true });
      continue;
    }

    // VEVRAA's veteran question quotes "entitled to compensation": a self-identification
    // question, and any choice control, is never a salary box.
    const selfIdentification = /\b(veteran|disabilit|gender|race|ethnic|hispanic)/i.test(label);
    const salaryQuestion = !selfIdentification && type !== "radio" && type !== "checkbox" &&
      /\b(salary|compensation|pay expectation|desired pay|pay rate|wages?)\b/i.test(label);
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

    const value = planned && planned.value === null ? "" : planned && planned.value ? planned.value : valueForKey(key);
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
        reason: planned && planned.value === null ? "No unique matching option" : "Profile field is blank",
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
        leftovers.push({ key, label, help: helpFor(el), type, options: Array.from(el.options).map((o) => o.text.trim()), required, selector: sel, reason: "No unique matching option" });
        if (required) required_empty.push(label || sel);
        continue;
      }
    } else if (type === "radio" || type === "checkbox") {
      const chosen = fillChoiceGroup(el, value, label, key);
      if (chosen === "skip") continue;
      if (!chosen) {
        leftovers.push({ key, label, help: helpFor(el), type, options: [], required, selector: sel, reason: "No exact matching choice" });
        if (required) required_empty.push(label || sel);
        continue;
      }
      written = String(value);
    } else if (eeo[key] && (value === "decline" || key === "veteran_status")) {
      // Declining picks a choice, and a veteran answer is a category
      // ("not_veteran"): neither is ever typed into a text box.
      leftovers.push({ key, label, type, options: [], required, selector: sel,
        reason: value === "decline" ? "Declined to self-identify" : "Self-identification needs a choice, not typed text" });
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
      if (key === "phone") textValue = phoneText(el, label, textValue);
      setNativeValue(el, textValue);
      written = textValue;
    }

    filled.push({ key, label, value: written, selector: sel });
  }

  if (scan) return { questions: questions_out, frames_skipped };
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
