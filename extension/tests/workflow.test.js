import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { advanceFollowUp, startFollowUp } from "../lib/workflow.js";

let local;
let session;
let posts;
let appStatus;
let active;

beforeEach(() => {
  local = { port: 8000, token: "secret" };
  session = {};
  posts = 0;
  appStatus = "jd_fetched";
  active = { action: "prepare", state: "running" };
  globalThis.chrome = {
    storage: {
      local: {
        get: async (key) => ({ [key]: local[key] }),
        set: async (value) => Object.assign(local, value),
        remove: async (key) => { delete local[key]; },
      },
      session: {
        get: async (keys) => Object.fromEntries(
          (Array.isArray(keys) ? keys : [keys]).map((key) => [key, session[key]]),
        ),
        set: async (value) => Object.assign(session, value),
        remove: async (key) => { delete session[key]; },
      },
    },
  };
  globalThis.fetch = async (url) => {
    if (url.endsWith("/api/health")) return { ok: true, json: async () => ({ app: "resumetailor" }) };
    if (url.endsWith("/status")) return { ok: true, json: async () => ({ workspace: "w1", paused: false, operation: active }) };
    if (url.includes("/lookup?")) return { ok: true, json: async () => ({ application: { id: "id1", status: appStatus, archived: false } }) };
    if (url.endsWith("/fill")) {
      posts += 1;
      return { ok: true, json: async () => ({ operation_id: "fill1" }) };
    }
    throw new Error(`Unexpected URL ${url}`);
  };
});

const pending = { applicationId: "id1", lookupUrl: "https://example.test/job", workspace: "w1", tabId: 1, operationId: "prep1" };

test("popup closure and concurrent alarms start only one fill", async () => {
  await startFollowUp(pending);
  await advanceFollowUp();
  assert.equal(posts, 0);
  active = null;
  appStatus = "ready";
  await Promise.all([advanceFollowUp(), advanceFollowUp()]);
  assert.equal(posts, 1);
  assert.equal(session.pendingFill, undefined);
});

test("an interrupted dispatch does not replay fill", async () => {
  await startFollowUp(pending);
  session.pendingFill.phase = "dispatching";
  active = null;
  appStatus = "ready";
  await advanceFollowUp();
  assert.equal(posts, 0);
  assert.match(session.lastResult, /Check ResumeTailor/);
});

test("workspace changes cancel queued fill", async () => {
  await startFollowUp({ ...pending, workspace: "w2" });
  active = null;
  appStatus = "ready";
  await advanceFollowUp();
  assert.equal(posts, 0);
  assert.equal(session.pendingFill, undefined);
});
