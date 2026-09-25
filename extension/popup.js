const content = document.querySelector("#content");
const errorBox = document.querySelector("#error");
const workspace = document.querySelector("#workspace");
let currentTab = null;
let state = null;
let poll = null;
let busy = false;
let unavailable = false;

function node(tag, text, className = "") {
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
    content.replaceChildren(
      node("p", "Start ResumeTailor first."),
      button("Retry", () => void refresh()),
    );
    showError(error.message);
  }
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
  const settings = node("a", "Open ResumeTailor settings");
  settings.href = `http://127.0.0.1:${state.port}/settings?tab=browser`;
  settings.target = "_blank";
  content.replaceChildren(hint, codeLabel, code, nameLabel, name, pairButton, settings);
}

async function runAction(action) {
  if (busy) return;
  busy = true;
  showError();
  try {
    const result = await rpc({ type: "action", action, tab: currentTab });
    state.lastResult = [result.message, ...(result.warnings || [])].join(" ");
    await refresh();
  } catch (error) {
    showError(error.message);
  } finally {
    busy = false;
  }
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
  if (page) {
    const app = page.lookup.application;
    parts.push(node("p", `Platform: ${page.lookup.ats || "unknown"}`));
    if (page.lookup.assist_only) {
      parts.push(node("p", "Assist only: review the form and submit it yourself.", "muted"));
    }
    if (app) {
      parts.push(node("p", `${app.company} · ${app.role} — ${app.status}`));
      if (app.needs_you) parts.push(node("p", `Needs you: ${app.needs_you}`, "notice"));
      if (app.screen_reasons?.length) parts.push(node("p", app.screen_reasons.join("; "), "muted"));
    }
    const actions = node("div", "", "row");
    actions.append(
      button("Send to ResumeTailor", () => void runAction("send")),
      button("Tailor now", () => void runAction("prepare"), true),
      button("Fill this page", () => void runAction("fill")),
    );
    parts.push(actions);
    if (app) {
      const link = node("a", "Open in app", "button");
      link.href = `http://127.0.0.1:${state.port}/applications/${encodeURIComponent(app.id)}`;
      link.target = "_blank";
      parts.push(link);
    }
    parts.push(node("p", "Fill uses the browser configured in ResumeTailor. Nothing is submitted automatically.", "muted"));
  } else {
    parts.push(node("p", "Open a job posting to capture it."));
  }
  content.replaceChildren(...parts);
}

function render() {
  workspace.textContent = "";
  if (state.state === "unpaired") renderUnpaired();
  else renderPaired();
}

void refresh();
poll = window.setInterval(() => { if (!busy && state?.state === "paired") void refresh(); }, 2000);
window.addEventListener("pagehide", () => window.clearInterval(poll));
