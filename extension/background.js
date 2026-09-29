import "./lib/sites.js";
import {
  ExtensionApiError, appUrl, captureStubs, findPort, lookup, lookupBatch, operation, pair, status,
} from "./lib/api.js";
import { captureTab, extractTab, lookupTab, readTabCards } from "./lib/capture.js";
import { advanceFollowUp, cancelFollowUp, startFollowUp } from "./lib/workflow.js";
import { connectRelay, relayAllowed } from "./lib/relay.js";
import { getOptions, setOptions } from "./lib/settings.js";
import { hasBoardAccess, syncBoardScripts } from "./lib/boards.js";
import { CompletionGuard, mergeCardStatus, shouldComplete, statusLabel } from "./lib/stubs.js";

const ALARM = "resume-tailor-status";
const COMMAND = "capture-page";
let actionBusy = false;
const completions = new CompletionGuard();

async function ensureAlarm() {
  if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { periodInMinutes: 1 });
}

async function updateBadge() {
  try {
    const current = await status();
    const badge = current.paused ? "II" : current.needs_you ? String(current.needs_you) : "";
    await chrome.action.setBadgeText({ text: badge });
    await chrome.action.setBadgeBackgroundColor({ color: current.paused ? "#9b6500" : "#a33330" });
  } catch {
    await chrome.action.setBadgeText({ text: "" });
  }
}

async function notify(message, title = "ResumeTailor") {
  try {
    await chrome.notifications.create({
      type: "basic", iconUrl: "icons/icon128.png", title, message, priority: 0,
    });
  } catch {
    // Notifications may be blocked by the OS; the popup still shows the last result.
  }
}

const RESULT_TEXT = {
  created: "Sent to ResumeTailor.",
  exists: "Already tracked in ResumeTailor.",
  completed: "Saved the description for a job you had saved from search results.",
  merged: "Linked this page to the job you already track.",
};

function describeResult(result) {
  const app = result.application;
  const parts = [RESULT_TEXT[result.result] || "Sent to ResumeTailor."];
  if (app?.status === "screened_out" && result.result !== "exists") {
    const reasons = app.screen_reasons.map((reason) => reason.replaceAll("_", " ")).join("; ");
    parts.push(`Screened out by your filters: ${reasons || "see the app"}.`);
  }
  return parts.join(" ");
}

// Capture, then run the "after capture" option (shortcut, context menu and page chip).
async function quickCapture(tab, selection = "") {
  const { result, data } = await captureTab(tab, selection);
  let message = describeResult(result);
  const options = await getOptions();
  const app = result.application;
  if (options.afterCapture === "send+tailor" && result.result !== "exists" &&
      app.status !== "screened_out" && !app.capture_stub) {
    try {
      await operation(app.id, "prepare");
      message += " Tailoring started.";
    } catch (error) {
      message += ` Tailoring did not start: ${error.message}`;
    }
  }
  const warnings = result.warnings || [];
  await chrome.storage.session.set({ lastResult: [message, ...warnings].join(" ") });
  return { message, warnings, result, data };
}

async function snapshot(tab) {
  const port = await findPort();
  const saved = await chrome.storage.local.get("token");
  const options = await getOptions();
  if (!saved.token) return { state: "unpaired", port, options };
  const current = await status();
  const page = tab && /^https?:\/\//.test(tab.url || "") ? await lookupTab(tab) : null;
  const session = await chrome.storage.session.get(["pendingFill", "lastResult"]);
  return {
    state: "paired", port, status: current, page, options,
    boardAccess: await hasBoardAccess(), relayAllowed: await relayAllowed(), ...session,
  };
}

function fillBlocked(app) {
  if (app?.apply_kind !== "easy_apply") return "";
  const board = app.ats === "indeed" ? "Indeed" : "LinkedIn";
  return `This job uses ${board}'s own apply form, so Fill cannot run. Tailor it, then apply on ${board}.`;
}

async function runAction(action, tab) {
  if (actionBusy) throw new Error("An action is already starting. Wait a moment.");
  actionBusy = true;
  try {
    const current = await status();
    let page = await lookupTab(tab);
    let captureResult = null;
    let app = page.lookup.application;
    if (action === "send" || !app || app.capture_stub) {
      captureResult = await captureTab(tab);
      app = captureResult.result.application;
      page = { ...page, data: captureResult.data };
    }
    if (action === "send") {
      const message = describeResult(captureResult.result);
      const warnings = captureResult.result.warnings || [];
      await chrome.storage.session.set({ lastResult: [message, ...warnings].join(" ") });
      return { message, warnings, result: captureResult.result.result, application: app };
    }
    if (app.archived) throw new Error("This application is archived. Open it in ResumeTailor.");
    if (action === "prepare") {
      const started = await operation(app.id, "prepare");
      await chrome.storage.session.set({ lastResult: "Tailoring started." });
      return { message: "Tailoring started.", operation: started, application: app };
    }
    if (action !== "fill") throw new Error("Unknown action.");
    const blocked = fillBlocked(app);
    if (blocked) throw new Error(blocked);
    if (app.status === "ready") {
      const started = await operation(app.id, "fill");
      await chrome.storage.session.set({ lastResult: "Fill started. You submit the application yourself." });
      return { message: "Fill started. You submit the application yourself.", operation: started, application: app };
    }
    const existing = await chrome.storage.session.get("pendingFill");
    if (existing.pendingFill) throw new Error("A fill is already waiting for preparation.");
    const started = await operation(app.id, "prepare");
    await startFollowUp({
      applicationId: app.id,
      lookupUrl: page.data?.apply_url || page.data?.final_url || tab.url,
      workspace: current.workspace,
      tabId: tab.id,
      operationId: started.operation_id,
    });
    return { message: "Preparing the application. Fill will start when it is ready.", operation: started, application: app };
  } finally {
    actionBusy = false;
  }
}

async function contextCapture(info, tab) {
  try {
    const pageTab = { ...tab, url: tab?.url || info.pageUrl };
    const { message } = await quickCapture(pageTab, info.menuItemId === "send-selection" ? info.selectionText || "" : "");
    await chrome.action.setTitle({ title: message });
    await notify(message);
  } catch (error) {
    await chrome.storage.session.set({ lastResult: error.message });
    await chrome.action.setTitle({ title: error.message });
    await notify(error.message, "ResumeTailor: not sent");
  }
}

async function commandCapture(command) {
  if (command !== COMMAND) return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const { message } = await quickCapture(tab);
    await notify(message);
  } catch (error) {
    await chrome.storage.session.set({ lastResult: error.message });
    await notify(error.message, "ResumeTailor: not sent");
  }
}

async function readCards(tab) {
  const cards = await readTabCards(tab);
  if (!cards.length) return { cards: [] };
  const { results } = await lookupBatch(cards.map((card) => card.url));
  return { cards: mergeCardStatus(cards, results) };
}

async function saveCards(cards) {
  const { results } = await captureStubs(cards);
  const count = (kind) => results.filter((item) => item.result === kind).length;
  const saved = count("created");
  const message = `Saved ${saved} job${saved === 1 ? "" : "s"}. ` +
    "Each one is completed when you open it." +
    (count("exists") ? ` ${count("exists")} already tracked.` : "") +
    (count("invalid") ? ` ${count("invalid")} could not be saved.` : "");
  await chrome.storage.session.set({ lastResult: message });
  return { message, results };
}

// A LinkedIn/Indeed job opened in a tab (from content.js): report its queue status,
// and send the description of a saved card once the pane has loaded it.
async function jobView(message, sender) {
  const tab = sender.tab;
  if (!tab?.id || sender.id !== chrome.runtime.id) return { state: "none" };
  const options = await getOptions();
  const { token } = await chrome.storage.local.get("token");
  if (!token) return { state: "unpaired", chip: options.pageChip };
  const found = await lookup(message.url);
  let app = found.application;
  let completed = false;
  if (app?.capture_stub && options.autoComplete && message.complete && completions.begin(message.key)) {
    try {
      const data = await extractTab(tab.id);
      const dataKey = globalThis.RTSites.jobFromUrl(data.url)?.key || "";
      if (shouldComplete({ application: app, jobKey: message.key, dataKey, description: data.jd_text })) {
        const { result } = await captureTab(tab, "", data);
        app = result.application;
        completed = true;
      }
    } finally {
      completions.done(message.key);
    }
  }
  return {
    state: "ok", application: app, completed, chip: options.pageChip, label: statusLabel(app),
  };
}

async function chipAction(message, sender) {
  const tab = sender.tab;
  if (!tab?.id || sender.id !== chrome.runtime.id) throw new Error("Unknown page.");
  if (message.action === "open") {
    await chrome.tabs.create({ url: await appUrl(`/applications/${encodeURIComponent(message.id)}`) });
    return {};
  }
  if (message.action === "tailor") return runAction("prepare", tab);
  if (message.action === "save") {
    const { message: text, result } = await quickCapture(tab);
    return { message: text, application: result.application };
  }
  if (message.action === "hide") return setOptions({ pageChip: false });
  throw new Error("Unknown action.");
}

async function install() {
  await chrome.contextMenus.removeAll();
  chrome.contextMenus.create({ id: "send-selection", title: "Send selection to ResumeTailor", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "send-page", title: "Send this page to ResumeTailor", contexts: ["page"] });
  await ensureAlarm();
  await syncBoardScripts().catch(() => {});
}

chrome.runtime.onInstalled.addListener(() => { void install(); });
chrome.runtime.onStartup.addListener(() => {
  void ensureAlarm();
  void syncBoardScripts().catch(() => {});
});
chrome.contextMenus.onClicked.addListener((info, tab) => { void contextCapture(info, tab); });
chrome.commands.onCommand.addListener((command) => { void commandCapture(command); });
chrome.permissions.onAdded.addListener(() => { void syncBoardScripts().catch(() => {}); });
chrome.permissions.onRemoved.addListener((removed) => {
  void syncBoardScripts().catch(() => {});
  if (removed.permissions?.includes("debugger")) void setOptions({ relay: false });
});
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== ALARM) return;
  void updateBadge();
  void advanceFollowUp().catch((error) => {
    if (error instanceof ExtensionApiError && error.code === "extension_auth") return;
    void chrome.storage.session.set({ lastResult: error.message });
  });
});
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Content scripts (on LinkedIn/Indeed) may send only their own two message types.
  const fromPage = !!sender.tab && !sender.url?.startsWith(`chrome-extension://${chrome.runtime.id}/`);
  if (fromPage && !["job-view", "chip"].includes(message?.type)) {
    sendResponse({ ok: false, error: "Not allowed." });
    return false;
  }
  (async () => {
    switch (message.type) {
      case "snapshot":
        await advanceFollowUp();
        return snapshot(message.tab);
      case "retry": return snapshot(message.tab);
      case "pair": {
        const result = await pair(message.code, message.label);
        await updateBadge();
        return { id: result.id };
      }
      case "action": return runAction(message.action, message.tab);
      case "cancel": await cancelFollowUp(); return {};
      case "relay": return connectRelay(message.tab);
      case "cards": return readCards(message.tab);
      case "save-cards": return saveCards(message.cards);
      case "job-view": return jobView(message, sender);
      case "chip": return chipAction(message, sender);
      default: throw new Error("Unknown extension request.");
    }
  })().then((value) => sendResponse({ ok: true, value }), (error) => sendResponse({
    ok: false, error: error.message, code: error.code || "",
  }));
  return true;
});

void chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" }).catch(() => {});
void ensureAlarm();
void updateBadge();
