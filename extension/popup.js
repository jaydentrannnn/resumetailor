import { requestBoardAccess } from "./lib/boards.js";
import { statusLabel } from "./lib/stubs.js";

const content = document.querySelector("#content");
const errorBox = document.querySelector("#error");
const workspace = document.querySelector("#workspace");
let currentTab = null;
let state = null;
let poll = null;
let busy = false;
let unavailable = false;
let last = null; // the last action's result: {message, application, result}
let cards = null; // search-page cards once listed: [{url, role, company, tracked, status, ...}]
const picked = new Set();

function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function button(label, click, primary = false) {
  const element = node("button", label, primary ? "primary" : "");
  element.type = "button";
  element.addEventListener("click", click);
  return element;
}

function link(label, href, className = "") {
  const element = node("a", label, className);
  element.href = href;
  element.target = "_blank";
  element.rel = "noreferrer";
  return element;
}

function optionsLink(label = "Options") {
  const element = node("a", label);
  element.href = "#";
  element.addEventListener("click", (event) => {
    event.preventDefault();
    void chrome.runtime.openOptionsPage();
  });
  return element;
}

function showError(message = "") {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function rpc(message) {
  return chrome.runtime.sendMessage(message).then((reply) => {
    if (!reply?.ok) {
      const error = new Error(reply?.error || "The extension is unavailable.");
      error.code = reply?.code || "";
      throw error;
    }
    return reply.value;
  });
}

const appLink = (path) => `http://127.0.0.1:${state.port}${path}`;
const itemLink = (app) => appLink(`/applications/${encodeURIComponent(app.link_id || app.id)}`);

async function refresh() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    currentTab = tab || null;
    state = await rpc({ type: "snapshot", tab: currentTab });
    if (unavailable) showError();
    unavailable = false;
    render();
  } catch (error) {
    if (error.code === "extension_auth") {
      state = await rpc({ type: "retry", tab: null });
      render();
      showError("Pair again.");
      return;
    }
    unavailable = true;
    renderNotRunning(error);
  }
}

function renderNotRunning(error) {
  workspace.textContent = "";
  const steps = node("ol", "", "steps");
  steps.append(
    node("li", "Open the ResumeTailor app, or start it with Docker or uvicorn."),
    node("li", "Keep it on this computer (127.0.0.1). The extension looks on ports 8000–8010."),
  );
  content.replaceChildren(
    node("p", "ResumeTailor is not running", "title"),
    steps,
    button("Try again", () => void refresh(), true),
    node("p", "Using another port? Set it in the extension options.", "muted"),
    optionsLink("Extension options"),
  );
  showError(error.code === "app_not_running" ? "" : error.message);
}

function renderUnpaired() {
  const hint = node("p", "Open Settings → Browser in ResumeTailor to get a six-digit code.", "muted");
  const codeLabel = node("label", "Pairing code");
  const code = document.createElement("input");
  code.id = "pair-code";
  code.inputMode = "numeric";
  code.maxLength = 6;
  code.pattern = "[0-9]{6}";
  code.autocomplete = "off";
  codeLabel.htmlFor = code.id;
  const nameLabel = node("label", "Browser name");
  const name = document.createElement("input");
  name.id = "browser-name";
  name.maxLength = 80;
  name.value = navigator.userAgent.includes("Edg/") ? "Edge" : "Chrome";
  nameLabel.htmlFor = name.id;
  const pairButton = button("Pair", async () => {
    if (!/^[0-9]{6}$/.test(code.value)) return showError("Enter all six digits of the code.");
    pairButton.disabled = true;
    try {
      await rpc({ type: "pair", code: code.value, label: name.value.trim() });
      showError();
      await refresh();
    } catch (error) {
      showError(error.message);
    } finally {
      pairButton.disabled = false;
    }
  }, true);
  content.replaceChildren(
    hint, codeLabel, code, nameLabel, name, pairButton,
    link("Open ResumeTailor settings", appLink("/settings?tab=browser")),
  );
}

async function runAction(action) {
  if (busy) return;
  busy = true;
  showError();
  try {
    last = await rpc({ type: "action", action, tab: currentTab });
    state.lastResult = [last.message, ...(last.warnings || [])].join(" ");
    await refresh();
  } catch (error) {
    showError(error.message);
  } finally {
    busy = false;
  }
}

function fillBlockedReason(app, data) {
  const kind = app?.apply_kind && app.apply_kind !== "unknown" ? app.apply_kind : data?.apply_kind;
  if (kind !== "easy_apply") return "";
  const board = (app?.ats || data?.site) === "indeed" ? "Indeed" : "LinkedIn";
  return `Easy Apply: apply on ${board} yourself. Tailor still works; Fill can't drive ${board}'s form.`;
}

// Screen reasons arrive as codes ("requires_4_years") or sentences; both read as text.
const reasons = (app) => (app.screen_reasons || []).map((reason) => reason.replaceAll("_", " ")).join("; ");

function appSummary(app) {
  const parts = [node("p", `${app.company} · ${app.role}`, "title")];
  parts.push(node("p", `Status: ${statusLabel(app)}`));
  if (app.capture_stub) {
    parts.push(node("p", "Saved from search results. Open this job to save its description.", "muted"));
  }
  if (app.status === "screened_out") {
    parts.push(node(
      "p",
      `Screened out by your filters: ${reasons(app) || "see the app for details"}. ` +
        "It won't be tailored automatically. Change the filters in ResumeTailor's Apply settings, then Retry it there.",
      "notice",
    ));
  } else if (app.screen_reasons?.length) {
    parts.push(node("p", reasons(app), "muted"));
  }
  if (app.needs_you) parts.push(node("p", `Needs you: ${app.needs_you}`, "notice"));
  if (app.apply_url) parts.push(node("p", `Apply page: ${new URL(app.apply_url).hostname}`, "muted"));
  parts.push(link("Open in app", itemLink(app), "button"));
  return parts;
}

function isJobPage(page) {
  if (page.lookup.application) return true;
  if (page.data?.job_key) return true;
  if (page.data?.site) return false; // a board page with no job open (search list, feed)
  return !["other", "unknown"].includes(page.lookup.ats);
}

function renderCards(parts) {
  const section = node("section", "", "cards");
  section.append(node("p", "Jobs on this page", "title"));
  if (!state.boardAccess) {
    section.append(
      node("p", "Allow LinkedIn and Indeed so saved jobs complete themselves when you open them.", "muted"),
      button("Allow on LinkedIn and Indeed", async () => {
        try {
          await requestBoardAccess();
          await refresh();
        } catch (error) {
          showError(error.message);
        }
      }),
    );
  }
  if (!cards) {
    section.append(button(`Show ${state.page.data.card_count} jobs to save`, async () => {
      try {
        cards = (await rpc({ type: "cards", tab: currentTab })).cards;
        picked.clear();
        cards.filter((card) => !card.tracked).forEach((card) => picked.add(card.url));
        render();
      } catch (error) {
        showError(error.message);
      }
    }));
    parts.push(section);
    return;
  }
  const list = node("ul", "", "card-list");
  for (const card of cards) {
    const item = node("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.id = `card-${card.job_id}`;
    box.checked = picked.has(card.url);
    box.disabled = card.tracked;
    box.addEventListener("change", () => {
      if (box.checked) picked.add(card.url);
      else picked.delete(card.url);
      save.disabled = !picked.size;
      save.textContent = `Save ${picked.size} selected`;
    });
    const label = node("label", "");
    label.htmlFor = box.id;
    label.append(node("span", card.role, "role"), node("span", [card.company, card.location].filter(Boolean).join(" · "), "muted"));
    if (card.tracked) label.append(node("span", `In queue · ${card.status}`, "tag"));
    item.append(box, label);
    list.append(item);
  }
  const save = button(`Save ${picked.size} selected`, async () => {
    save.disabled = true;
    try {
      const chosen = cards.filter((card) => picked.has(card.url));
      const result = await rpc({ type: "save-cards", cards: chosen });
      state.lastResult = result.message;
      cards = null;
      await refresh();
    } catch (error) {
      showError(error.message);
      save.disabled = false;
    }
  }, true);
  save.disabled = !picked.size;
  section.append(
    cards.length ? list : node("p", "No job cards are visible. Scroll the results, then try again.", "muted"),
    save,
    node("p", "Saved jobs appear under Needs description in ResumeTailor.", "muted"),
  );
  parts.push(section);
}

function renderAdvanced(parts) {
  const details = node("details", "", "advanced");
  details.append(node("summary", "Advanced"));
  if (state.options.relay && state.relayAllowed) {
    details.append(button("Use this tab for Fill (relay)", async () => {
      try {
        const result = await rpc({ type: "relay", tab: currentTab });
        state.lastResult = result.message;
        render();
      } catch (error) {
        showError(error.message);
      }
    }));
  } else {
    details.append(node("p", "The Fill relay is off. Turn it on in the options.", "muted"));
  }
  details.append(optionsLink("Extension options"));
  parts.push(details);
}

function renderPaired() {
  const current = state.status;
  const page = state.page;
  workspace.textContent = current.workspace || "";
  const parts = [];
  if (current.paused) parts.push(node("p", "Automation paused", "notice"));
  if (current.operation) {
    parts.push(node("p", `${current.operation.action}: ${current.operation.message || current.operation.state} (${current.operation.processed}/${current.operation.total})`, "notice"));
  }
  if (state.pendingFill) {
    parts.push(node("p", "Preparing this application. Fill will start once it is ready.", "notice"));
    parts.push(button("Cancel pending fill", async () => {
      await rpc({ type: "cancel" });
      await refresh();
    }));
  }
  if (state.lastResult) parts.push(node("p", state.lastResult, "notice"));
  if (last?.application && ["exists", "merged", "completed"].includes(last.result) &&
      last.application.id !== page?.lookup.application?.id) {
    parts.push(link("Open the tracked job", itemLink(last.application)));
  }
  if (!page) {
    parts.push(node("p", "Open a job posting to capture it."));
  } else {
    const app = page.lookup.application;
    if (page.data?.card_count && !page.data.job_key) renderCards(parts);
    if (isJobPage(page)) {
      if (page.lookup.assist_only) {
        parts.push(node("p", "Assist only: review the form and submit it yourself.", "muted"));
      }
      if (app) parts.push(...appSummary(app));
      const actions = node("div", "", "row");
      if (!app || app.capture_stub) {
        actions.append(button(app ? "Save description" : "Send to ResumeTailor", () => void runAction("send"), !app));
      }
      const blocked = fillBlockedReason(app, page.data);
      if (!app || app.status !== "screened_out") {
        actions.append(button("Tailor now", () => void runAction("prepare"), !!app));
        const fill = button("Fill this page", () => void runAction("fill"));
        fill.disabled = !!blocked;
        if (blocked) fill.title = blocked;
        actions.append(fill);
      }
      if (actions.childElementCount) parts.push(actions);
      if (blocked) parts.push(node("p", blocked, "muted"));
      parts.push(node("p", "Nothing is submitted automatically.", "muted"));
      if (page.data?.card_count) renderCards(parts);
    } else if (!page.data?.card_count) {
      parts.push(node("p", "This page doesn't look like a job posting."));
      const more = node("details");
      more.append(
        node("summary", "Send it anyway"),
        button("Send to ResumeTailor", () => void runAction("send")),
      );
      parts.push(more);
    }
    renderAdvanced(parts);
  }
  content.replaceChildren(...parts);
}

function render() {
  workspace.textContent = "";
  if (state.state === "unpaired") renderUnpaired();
  else renderPaired();
}

void refresh();
// Poll while nothing is being chosen, so a card list or input is never reset mid-use.
poll = window.setInterval(() => {
  if (!busy && !cards && state?.state === "paired") void refresh();
}, 2000);
window.addEventListener("pagehide", () => window.clearInterval(poll));
