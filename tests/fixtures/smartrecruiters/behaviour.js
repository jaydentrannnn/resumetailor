// Stand-in for the spl-* components' behaviour over the captured (static) markup, as
// observed live on 2026-09-27. Only what the fill depends on is modelled:
// - a typeahead lists options in its own shadow root; only a trusted press commits one
//   (dispatched events are ignored live), setting the host's `value`; uncommitted text
//   is dropped on blur;
// - Add opens an inline editor; Save keeps it open unless the required fields are set,
//   otherwise renders a saved entry; Cancel removes it;
// - a month picker takes typed "MM/YYYY" + Enter;
// - a dropzone lists the chosen file's name in its shadow root.
// window.__sr = {catalog: {dataTest: [[value, text]]}, locations: {value: object},
//                editors: {experience: html, education: html}} is set by the test.
(() => {
  const sr = window.__sr;
  sr.uploads = [];
  sr.saves = 0;
  const deep = (root, sel, out = []) => {
    out.push(...root.querySelectorAll(sel));
    for (const el of root.querySelectorAll("*")) if (el.shadowRoot) deep(el.shadowRoot, sel, out);
    return out;
  };
  const find = (path, tag) => path.find((n) => n.tagName === tag);
  const text = (s) => String(s || "").replace(/\s+/g, " ").trim();

  const init = (root) => {
    for (const ac of deep(root, "spl-autocomplete")) if (!("value" in ac)) ac.value = null;
    for (const input of deep(root, "input[type=file]")) {
      const owner = input.getRootNode().host;
      if (input.__sr || !owner || owner.tagName !== "SPL-DROPZONE") continue;
      input.__sr = true;
      input.addEventListener("change", () => {
        const zone = input.getRootNode().host;
        const name = input.files[0] ? input.files[0].name : "";
        sr.uploads.push(`${zone.getAttribute("data-test")}:${name}`);
        let list = zone.shadowRoot.querySelector("ul.c-spl-file-list");
        if (!list) {
          list = document.createElement("ul");
          list.className = "c-spl-file-list";
          input.parentNode.appendChild(list);
        }
        list.insertAdjacentHTML("beforeend",
          `<li class="c-spl-file-list-item"><span class="c-spl-file-list-item-name">${name}</span></li>`);
        input.value = "";
      });
    }
  };

  const menuOf = (ac) => ac.shadowRoot.querySelector("spl-dropdown");
  const closeMenu = (ac) => menuOf(ac).querySelectorAll("[slot=menu]").forEach((m) => m.remove());
  const render = (ac, query) => {
    closeMenu(ac);
    if (!query) return;
    const kind = ac.getAttribute("data-test");
    const q = query.toLowerCase();
    let options;
    if (kind === "location-autocomplete") {
      options = Object.entries(sr.locations)
        .filter(([, loc]) => loc.city.toLowerCase().startsWith(q))
        .map(([value, loc]) => [value, loc.displayString]);
      options.push(["goToManualLocationMode", "Cannot find your city? Click here to fill in manually"]);
    } else {
      options = (sr.catalog[kind] || []).filter(([value]) => value.toLowerCase().startsWith(q));
      // Live: the typed-text option is offered unless the catalog spells it exactly.
      if (!options.some(([value]) => value.toLowerCase() === q)) options.unshift(["#spl-custom-option", query]);
    }
    const menu = document.createElement("div");
    menu.setAttribute("slot", "menu");
    menu.setAttribute("role", "listbox");
    for (const [value, label] of options) {
      const option = document.createElement("spl-select-option");
      option.setAttribute("value", value);
      option.innerHTML = `<div class="c-spl-autocomplete-default-option">${label}</div>`;
      menu.appendChild(option);
    }
    menuOf(ac).appendChild(menu);
  };

  document.addEventListener("input", (e) => {
    const path = e.composedPath();
    const ac = find(path, "SPL-AUTOCOMPLETE");
    if (!ac || path[0].getAttribute("role") !== "combobox") return;
    ac.value = null;
    clearTimeout(ac.__timer);
    ac.__timer = setTimeout(() => render(ac, path[0].value), 120);
  }, true);

  document.addEventListener("mousedown", (e) => {
    const path = e.composedPath();
    const option = find(path, "SPL-SELECT-OPTION");
    const ac = find(path, "SPL-AUTOCOMPLETE");
    if (!option || !ac || !e.isTrusted) return;
    e.preventDefault();  // the input keeps focus, as live
    const value = option.getAttribute("value");
    if (value === "goToManualLocationMode") return;
    const input = deep(ac.shadowRoot, "input[role=combobox]")[0];
    if (ac.getAttribute("data-test") === "location-autocomplete") {
      ac.value = sr.locations[value];
      input.value = ac.value.displayString;
    } else {
      ac.value = value === "#spl-custom-option" ? text(option.textContent) : value;
      input.value = ac.value;
    }
    closeMenu(ac);
  }, true);

  document.addEventListener("focusout", (e) => {
    const path = e.composedPath();
    const ac = find(path, "SPL-AUTOCOMPLETE");
    if (!ac || path[0].getAttribute("role") !== "combobox") return;
    setTimeout(() => {
      if (!ac.value) path[0].value = "";
      closeMenu(ac);
    }, 30);
  }, true);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const path = e.composedPath();
    const field = find(path, "SPL-DATE-FIELD");
    if (!field) return;
    const match = /^(\d{2})\/(\d{4})$/.exec(path[0].value);
    field.value = match ? `${match[2]}-${match[1]}` : null;
    if (!match) path[0].value = "";
  }, true);

  // `host` then `inner` (which may sit in the host's shadow root): a descendant
  // selector does not cross a shadow boundary.
  const inside = (entry, host, inner) => {
    const found = deep(entry, host)[0];
    return found && inner ? deep(found.shadowRoot || found, inner)[0] || deep(found, inner)[0] : found;
  };
  const year = (value) => (value || "").slice(0, 4);
  const save = (kind, entry) => {
    const ac = (test) => { const el = inside(entry, `spl-autocomplete[data-test=${test}]`); return el ? el.value : null; };
    const date = (test) => { const el = inside(entry, `oc-datepicker[data-test=${test}] spl-date-field`); return el ? el.value : null; };
    const box = inside(entry, `oc-checkbox[data-test=${kind}-current]`, "input[type=checkbox]");
    const current = !!(box && box.checked);
    const area = inside(entry, "textarea");
    const description = area ? area.value : "";
    const from = date(`${kind}-date-from`), to = date(`${kind}-date-to`);
    let html;
    if (kind === "experience") {
      const title = ac("job-title-autocomplete");
      if (!title || !from || !(to || current)) return false;
      const company = ac("company-autocomplete") || "";
      html = `<oc-experience-entry data-test="experience-entry"><div data-test="experience-entry"><div data-test="experience-entry-is-edit-enabled"><p data-test="experience-entry-title"> ${title} <span data-test="experience-entry-date">${year(from)} - ${current ? "Present" : year(to)}</span></p><p data-test="experience-entry-company"> ${company} </p><p data-test="experience-entry-description">${description}</p></div></div></oc-experience-entry>`;
    } else {
      const school = ac("institution-autocomplete");
      if (!school) return false;
      const major = inside(entry, "oc-input[data-test=education-major]", "input").value;
      const degree = inside(entry, "oc-input[data-test=education-degree]", "input").value;
      html = `<oc-education-entry data-test="experience-entry"><div data-test="education-entry"><div data-test="education-entry-is-edit-enabled"><p data-test="education-entry-institution"> ${school} <span data-test="education-entry-date">${year(from)} - ${year(to)}</span></p><p data-test="education-entry-major"> ${major} </p><p data-test="education-entry-degree"> ${degree} </p><p data-test="education-entry-description">${description}</p></div></div></oc-education-entry>`;
    }
    entry.insertAdjacentHTML("afterend", html);
    entry.remove();
    sr.saves += 1;
    return true;
  };

  document.addEventListener("click", (e) => {
    const path = e.composedPath();
    const button = find(path, "OC-BUTTON");
    if (!button) return;
    const test = button.getAttribute("data-test") || "";
    const added = /^add-(experience|education)$/.exec(test);
    if (added) {
      const section = document.querySelector(`div[data-test=${added[1]}]`);
      const holder = document.createElement("div");
      holder.setHTMLUnsafe(sr.editors[added[1]]);
      const entry = holder.firstElementChild;
      section.appendChild(entry);
      init(entry);
      return;
    }
    const action = /^(experience|education)-(save|cancel)$/.exec(test);
    if (!action) return;
    const entry = button.closest("oc-experience-entry, oc-education-entry");
    if (action[2] === "cancel") entry.remove();
    else if (!save(action[1], entry)) entry.setAttribute("data-invalid", "");
  }, true);

  init(document);
})();
