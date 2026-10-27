import { lookup, operation, status } from "./api.js";
import { changePending, readPending } from "./pending.js";

// "Fill this page" on a row that is not ready yet: Prepare runs first, then Fill starts
// here once the row is ready. Each application waits on its own (`pendingFills`, keyed by
// application id), every status has a next step, and every wait has a time limit, so a
// follow-up never sits silently or blocks the next one (audit #26). Each wait carries a
// token: a step that looked the row up acts only if that same wait is still there, so a
// Cancel during the lookup is final.

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

/** Change `pending`'s entry with `update(all, stored)` while it is still that wait (not
 * cancelled, not started again); true when it was and `update` did not return false. */
function ifStill(pending, update) {
  return changePending((all) => {
    const stored = all[pending.applicationId];
    if (!stored || stored.token !== pending.token) return false;
    return update(all, stored) !== false;
  });
}

/** End this wait with `message`; null (and no message) when it was cancelled meanwhile. */
async function finish(pending, message) {
  const ended = await ifStill(pending, (all) => { delete all[pending.applicationId]; });
  if (!ended) return null;
  await chrome.storage.session.set({ lastResult: message });
  return message;
}

export async function startFollowUp({ applicationId, lookupUrl, workspace, tabId, operationId }) {
  await changePending((all) => {
    if (all[applicationId]) throw new Error("This application is already waiting to Fill.");
    all[applicationId] = {
      applicationId, lookupUrl, workspace, tabId, operationId, phase: "preparing",
      startedAt: Date.now(), token: crypto.randomUUID(),
    };
  });
  await chrome.storage.session.set({
    lastResult: "Preparing the application. Fill will start when it is ready.",
  });
}

/** Cancel one application's pending fill, or every one when no id is given. */
export async function cancelFollowUp(applicationId) {
  await changePending((all) => {
    for (const id of applicationId ? [applicationId] : Object.keys(all)) delete all[id];
  });
  await chrome.storage.session.set({
    lastResult: "Automatic fill cancelled. Any operation already started continues in ResumeTailor.",
  });
}

async function dispatch(pending, app, mode) {
  // Marked before the POST, and only while the wait is still there: a Cancel while the
  // row was looked up sends nothing.
  const claimed = await ifStill(pending, (all, stored) => {
    if (stored.phase === "dispatching") return false;
    all[pending.applicationId] = { ...stored, phase: "dispatching" };
  });
  if (!claimed) return null;
  try {
    await operation(app.id, "fill", mode);
    return finish(pending, mode === "continue"
      ? "Fill continued in the application's tab. Review the form before submitting it yourself."
      : "Fill started. Review the form before submitting it yourself.");
  } catch (error) {
    if (error.status === 409) {
      // Busy (another task has it, or the browser): try again on the next alarm.
      await ifStill(pending, (all, stored) => {
        all[pending.applicationId] = { ...stored, phase: "waiting" };
      });
      return null;
    }
    return finish(pending, error.status === 0
      ? "Check ResumeTailor before retrying Fill; its request may have started."
      : error.message);
  }
}

/** One step for one pending fill; resolves to the message when it finished, else null. */
async function advanceOne(pending, current) {
  const id = pending.applicationId;
  if (current.workspace !== pending.workspace) return finish(pending, "Workspace changed. Automatic fill cancelled.");
  if (Date.now() - pending.startedAt > FOLLOW_UP_LIMIT_MS) {
    return finish(pending, "The application did not get ready in time. Check it in ResumeTailor.");
  }
  if (pending.phase === "dispatching") {
    // The POST may have been accepted before the worker was suspended. Never send it twice.
    return finish(pending, "Check ResumeTailor before retrying Fill; its previous request may have started.");
  }
  const app = (await lookup(pending.lookupUrl)).application;
  if (!app || app.id !== id) return finish(pending, "Application could not be found. Check it in ResumeTailor.");
  if (app.archived || FINAL_STATUSES.has(app.status)) return finish(pending, `Automatic fill stopped: ${app.status.replaceAll("_", " ")}.`);
  if (current.paused) return null;
  if (app.status === "ready") return dispatch(pending, app, "initial");
  if (CONTINUE_STATUSES.has(app.status)) return dispatch(pending, app, "continue");
  if (app.status === "filling") return null;
  if (app.status === "submit_unconfirmed") {
    return finish(pending, "This application may already be submitted. Check it in ResumeTailor.");
  }
  if (PREPARING_STATUSES.has(app.status)) {
    if (!current.operation && Date.now() - pending.startedAt > STALLED_MS) {
      return finish(pending, "Preparation stopped before the application was ready. Check it in ResumeTailor.");
    }
    return null;
  }
  return finish(pending, `Automatic fill stopped: ${String(app.status).replaceAll("_", " ")}.`);
}

async function advance() {
  const pending = Object.values(await readPending());
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
