import { lookup, operation, status } from "./api.js";

let advancing = null;
const FINAL_STATUSES = new Set(["screened_out", "tailor_failed", "submitted", "skipped", "interview", "rejected", "ghosted"]);

async function finish(message) {
  await chrome.storage.session.remove("pendingFill");
  await chrome.storage.session.set({ lastResult: message });
}

export async function startFollowUp({ applicationId, lookupUrl, workspace, tabId, operationId }) {
  const current = await chrome.storage.session.get("pendingFill");
  if (current.pendingFill) throw new Error("A fill is already waiting for preparation.");
  await chrome.storage.session.set({
    pendingFill: { applicationId, lookupUrl, workspace, tabId, operationId, phase: "preparing", startedAt: Date.now() },
    lastResult: "Preparing the application. Fill will start when it is ready.",
  });
}

export async function cancelFollowUp() {
  await finish("Automatic fill cancelled. Any operation already started continues in ResumeTailor.");
}

async function advance() {
  const { pendingFill: pending } = await chrome.storage.session.get("pendingFill");
  if (!pending) return;
  const current = await status();
  if (current.workspace !== pending.workspace) {
    await finish("Workspace changed. Automatic fill cancelled.");
    return;
  }
  const page = await lookup(pending.lookupUrl);
  const app = page.application;
  if (!app || app.id !== pending.applicationId) {
    await finish("Application could not be found. Check it in ResumeTailor.");
    return;
  }
  if (app.archived || FINAL_STATUSES.has(app.status)) {
    await finish(`Automatic fill stopped: ${app.status}.`);
    return;
  }
  if (pending.phase === "dispatching") {
    // The POST may have been accepted before the worker was suspended. Never send it twice.
    await finish("Check ResumeTailor before retrying Fill; its previous request may have started.");
    return;
  }
  if (current.paused || current.operation) return;
  if (app.status !== "ready") {
    if (Date.now() - pending.startedAt > 30_000 &&
        (app.status === "jd_fetched" || app.status === "screened_in" || app.status === "tailoring")) {
      await finish("Preparation stopped before the application was ready. Check it in ResumeTailor.");
    }
    return;
  }
  await chrome.storage.session.set({ pendingFill: { ...pending, phase: "dispatching" } });
  try {
    await operation(app.id, "fill");
    await finish("Fill started. Review the form before submitting it yourself.");
  } catch (error) {
    if (error.status === 409) {
      await chrome.storage.session.set({ pendingFill: { ...pending, phase: "waiting" } });
      return;
    }
    await finish(error.status === 0
      ? "Check ResumeTailor before retrying Fill; its request may have started."
      : error.message);
  }
}

export function advanceFollowUp() {
  if (!advancing) advancing = advance().finally(() => { advancing = null; });
  return advancing;
}
