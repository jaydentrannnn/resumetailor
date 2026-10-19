  // dom_common.js: page helpers shared by filler.js, filler_readiness.js and
  // page_blockers. `fill_page.with_dom_common` puts this text in place of each script's
  // DOM_COMMON marker, inside that script's own function, so the `isVisible` and
  // `labelFor` used below are that script's own.

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

  /** React Select's own control box (``select__control``, or an emotion ``css-…-control``
   * holding a value container), not any class ending in "-control": Jobvite wraps every
   * field in ``jv-form-field-control``. */
  const REACT_SELECT_CLASS = /(?:^|\s)(?:[\w-]*select__control|css-\w+-control)(?:\s|$)/;
  function reactSelectBox(el) {
    const box = el.closest("[class*='select__control'], [class*='-control']");
    if (!box) return null;
    if (REACT_SELECT_CLASS.test(box.getAttribute("class") || "")) return box;
    return box.querySelector("[class*='alueContainer'], [class*='value-container'], [class*='ndicatorsContainer']") ? box : null;
  }

  const TRIGGERS = "[role='combobox'], [aria-haspopup='listbox'], input[id^='react-select-']";

  /**
   * The dropdown a validity stand-in belongs to: an input hidden from assistive tech and
   * the tab order (``aria-hidden``, ``tabindex=-1``) beside one visible dropdown trigger in
   * the same widget (Greenhouse's ``requiredInput``). Such an input is that dropdown, not
   * a question of its own; a hidden native control that is a widget's only control is.
   */
  function twinOwner(el) {
    if (el.tagName !== "INPUT" || el.getAttribute("aria-hidden") !== "true" || el.tabIndex !== -1) return null;
    if (el.matches(TRIGGERS) || (el.id && rootOf(el).querySelector(`label[for="${CSS.escape(el.id)}"]`))) return null;
    for (let node = el.parentElement, depth = 0; node && node !== document.body && depth < 4; node = node.parentElement, depth++) {
      const triggers = Array.from(node.querySelectorAll(TRIGGERS)).filter((other) => other !== el && isVisible(other));
      if (triggers.length) return triggers.length === 1 ? triggers[0] : null;
    }
    return null;
  }

  /** Hidden from people while still "visible" to scripts: off-screen, see-through, tiny. */
  function hiddenFromPeople(el) {
    const rect = el.getBoundingClientRect();
    if (rect.width <= 2 || rect.height <= 2 || rect.right <= 0 || rect.bottom <= 0) return true;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (getComputedStyle(node).opacity === "0" || node.getAttribute("aria-hidden") === "true") return true;
    }
    return false;
  }

  /** A trap for bots: never filled, never reported (Workday's ``beecatcher``). */
  const TRAP_NAME = /honey\s*pot|beecatcher|bot[-_ ]?trap/i;
  const TRAP_TEXT = /leave (?:this |it )?(?:field |box )?(?:blank|empty)|for robots|do not (?:fill|enter|type)|if you are (?:a )?human/i;
  function honeypot(el) {
    const ident = `${el.getAttribute("name") || ""} ${el.id || ""} ${el.getAttribute("class") || ""}`;
    if (TRAP_NAME.test(ident)) return true;
    return hiddenFromPeople(el) && TRAP_TEXT.test(`${labelFor(el)} ${el.getAttribute("placeholder") || ""}`);
  }
