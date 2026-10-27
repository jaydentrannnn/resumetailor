import { lookup, operation, status } from "./api.js";

// "Fill this page" on a row that is not ready yet: Prepare runs first, then Fill starts
// here once the row is ready. Each application waits on its own (`pendingFills`, keyed by
// application id), every status has a next step, and every wait has a time limit, so a
// follow-up never sits silently or blocks the next one (audit #26).

const KEY = "pendingFills";
/** A pending fill gives up after this long, whatever it waits for. */
export const FOLLOW_UP_LIMIT_MS = 20 * 60_000;
/** Preparation that stopped (no task running, row not moving) is reported after this. */
const STALLED_MS = 30_000;

const FINAL_STATUSES = new Set(["screened_out", "tailor_failed", "submitted", "skipped", "interview", "rejected", "ghosted"]);
/** A fill stopped there earlier: Fill continues it in its tab. */
const CONTINUE_STATUSES = new Set(["awaiting_review", "awaiting_otp", "fill_failed"]);
/** Still on the way to ready. */
const PREPARING_STATUSES = new Set(["discovered", "jd_fetched", "screened_in", "tailoring"]);

let advancing = null;

async function pendingFills() {
  const { [KEY]: pending } = await chrome.storage.session.get(KEY);
  return pending && typeof pending === "object" ? pending : {};
}

async function save(applicationId, value) {
  const pending = await pendingFills();
  if (value) pending[applicationId] = value;
  else delete pending[applicationId];
  await chrome.storage.session.set({ [KEY]: pending });
}

async function finish(applicationId, message) {
  await save(applicationId, null);
  await chrome.storage.session.set({ lastResult: message });
  return message;
}

export async function startFollowUp({ applicationId, lookupUrl, workspace, tabId, operationId }) {
  const pending = await pendingFills();
  if (pending[applicationId]) throw new Error("This application is already waiting to Fill.");
  await save(applicationId, {
    applicationId, lookupUrl, workspace, tabId, operationId, phase: "preparing", startedAt: Date.now(),
  });
  await chrome.storage.session.set({
    lastResult: "Preparing the application. Fill will start when it is ready.",
  });
}

/** Cancel one application's pending fill, or every one when no id is given. */
export async function cancelFollowUp(applicationId) {
  const pending = await pendingFills();
  const ids = applicationId ? [applicationId] : Object.keys(pending);
  for (const id of ids) await save(id, null);
  await chrome.storage.session.set({
    lastResult: "Automatic fill cancelled. Any operation already started continues in ResumeTailor.",
  });
}

async function dispatch(pending, app, mode) {
  await save(app.id, { ...pending, phase: "dispatching" });
  try {
    await operation(app.id, "fill", mode);
    return finish(app.id, mode === "continue"
      ? "Fill continued in the application's tab. Review the form before submitting it yourself."
      : "Fill started. Review the form before submitting it yourself.");
  } catch (error) {
    if (error.status === 409) {
      // Busy (another task has it, or the browser): try again on the next alarm.
      await save(app.id, { ...pending, phase: "waiting" });
      return null;
    }
    return finish(app.id, error.status === 0
      ? "Check ResumeTailor before retrying Fill; its request may have started."
      : error.message);
  }
}

/** One step for one pending fill; resolves to the message when it finished, else null. */
async function advanceOne(pending, current) {
  const id = pending.applicationId;
  if (current.workspace !== pending.workspace) return finish(id, "Workspace changed. Automatic fill cancelled.");
  if (Date.now() - pending.startedAt > FOLLOW_UP_LIMIT_MS) {
    return finish(id, "The application did not get ready in time. Check it in ResumeTailor.");
  }
  if (pending.phase === "dispatching") {
    // The POST may have been accepted before the worker was suspended. Never send it twice.
    return finish(id, "Check ResumeTailor before retrying Fill; its previous request may have started.");
  }
  const app = (await lookup(pending.lookupUrl)).application;
  if (!app || app.id !== id) return finish(id, "Application could not be found. Check it in ResumeTailor.");
  if (app.archived || FINAL_STATUSES.has(app.status)) return finish(id, `Automatic fill stopped: ${app.status.replaceAll("_", " ")}.`);
  if (current.paused) return null;
  if (app.status === "ready") return dispatch(pending, app, "initial");
  if (CONTINUE_STATUSES.has(app.status)) return dispatch(pending, app, "continue");
  if (app.status === "filling") return null;
  if (app.status === "submit_unconfirmed") {
    return finish(id, "This application may already be submitted. Check it in ResumeTailor.");
  }
  if (PREPARING_STATUSES.has(app.status)) {
    if (!current.operation && Date.now() - pending.startedAt > STALLED_MS) {
      return finish(id, "Preparation stopped before the application was ready. Check it in ResumeTailor.");
    }
    return null;
  }
  return finish(id, `Automatic fill stopped: ${String(app.status).replaceAll("_", " ")}.`);
}

async function advance() {
  const pending = Object.values(await pendingFills());
  if (!pending.length) return [];
  const current = await status();
  const finished = [];
  for (const item of pending) {
    const message = await advanceOne(item, current);
    if (message) finished.push(message);
  }
  return finished;
}

/** Advance every pending fill once; resolves to the messages of those that finished. */
export function advanceFollowUp() {
  if (!advancing) advancing = advance().finally(() => { advancing = null; });
  return advancing;
}
