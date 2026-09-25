import { ExtensionApiError, findPort, lookup, operation, pair, status } from "./lib/api.js";
import { captureTab, lookupTab } from "./lib/capture.js";
import { advanceFollowUp, cancelFollowUp, startFollowUp } from "./lib/workflow.js";

const ALARM = "resume-tailor-status";
let actionBusy = false;

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

async function snapshot(tab) {
  const port = await findPort();
  const saved = await chrome.storage.local.get("token");
  if (!saved.token) return { state: "unpaired", port };
  const current = await status();
  const page = tab ? await lookupTab(tab) : null;
  const session = await chrome.storage.session.get(["pendingFill", "lastResult"]);
  return { state: "paired", port, status: current, page, ...session };
}

async function runAction(action, tab) {
  if (actionBusy) throw new Error("An action is already starting. Wait a moment.");
  actionBusy = true;
  try {
    const current = await status();
    let page = await lookupTab(tab);
    let captureResult = null;
    let app = page.lookup.application;
    if (action === "send" || !app) {
      captureResult = await captureTab(tab);
      app = captureResult.result.application;
      page = { ...page, data: captureResult.data };
    }
    if (action === "send") {
      const message = captureResult.result.result === "exists"
        ? "Already tracked in ResumeTailor."
        : "Sent to ResumeTailor.";
      const warnings = captureResult.result.warnings || [];
      await chrome.storage.session.set({ lastResult: [message, ...warnings].join(" ") });
      return { message, warnings };
    }
    if (app.archived) throw new Error("This application is archived. Open it in ResumeTailor.");
    if (action === "prepare") {
      const started = await operation(app.id, "prepare");
      await chrome.storage.session.set({ lastResult: "Tailoring started." });
      return { message: "Tailoring started.", operation: started };
    }
    if (action !== "fill") throw new Error("Unknown action.");
    if (app.status === "ready") {
      const started = await operation(app.id, "fill");
      await chrome.storage.session.set({ lastResult: "Fill started. You submit the application yourself." });
      return { message: "Fill started. You submit the application yourself.", operation: started };
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
    return { message: "Preparing the application. Fill will start when it is ready.", operation: started };
  } finally {
    actionBusy = false;
  }
}

async function contextCapture(info, tab) {
  try {
    const pageTab = { ...tab, url: tab?.url || info.pageUrl };
    const { result } = await captureTab(pageTab, info.menuItemId === "send-selection" ? info.selectionText || "" : "");
    const message = result.result === "exists" ? "Already tracked in ResumeTailor." : "Sent to ResumeTailor.";
    await chrome.storage.session.set({ lastResult: [message, ...(result.warnings || [])].join(" ") });
    await chrome.action.setTitle({ title: message });
  } catch (error) {
    await chrome.storage.session.set({ lastResult: error.message });
    await chrome.action.setTitle({ title: error.message });
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "send-selection", title: "Send selection to ResumeTailor", contexts: ["selection"] });
  chrome.contextMenus.create({ id: "send-page", title: "Send this page to ResumeTailor", contexts: ["page"] });
  void ensureAlarm();
});
chrome.runtime.onStartup.addListener(() => { void ensureAlarm(); });
chrome.contextMenus.onClicked.addListener((info, tab) => { void contextCapture(info, tab); });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== ALARM) return;
  void updateBadge();
  void advanceFollowUp().catch((error) => {
    if (error instanceof ExtensionApiError && error.code === "extension_auth") return;
    void chrome.storage.session.set({ lastResult: error.message });
  });
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
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
