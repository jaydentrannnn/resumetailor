import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { advanceFollowUp, cancelFollowUp, FOLLOW_UP_LIMIT_MS, startFollowUp } from "../lib/workflow.js";

let local;
let session;
let posts;
let apps;
let active;
let fillResponse;

beforeEach(() => {
  local = { port: 8000, token: "secret" };
  session = {};
  posts = [];
  apps = { "https://example.test/job": { id: "id1", status: "jd_fetched", archived: false } };
  active = { action: "prepare", state: "running" };
  fillResponse = () => ({ ok: true, json: async () => ({ operation_id: "fill1" }) });
  globalThis.chrome = {
    storage: {
      local: {
        get: async (key) => ({ [key]: local[key] }),
        set: async (value) => Object.assign(local, value),
        remove: async (key) => { delete local[key]; },
      },
      session: {
        get: async (keys) => Object.fromEntries(
          (Array.isArray(keys) ? keys : [keys]).map((key) => [key, structuredClone(session[key])]),
        ),
        set: async (value) => Object.assign(session, structuredClone(value)),
        remove: async (key) => { delete session[key]; },
      },
    },
  };
  globalThis.fetch = async (url) => {
    if (url.endsWith("/api/health")) return { ok: true, json: async () => ({ app: "resumetailor" }) };
    if (url.endsWith("/status")) return { ok: true, json: async () => ({ workspace: "w1", paused: false, operation: active }) };
    if (url.includes("/lookup?")) {
      const page = new URL(url).searchParams.get("url");
      return { ok: true, json: async () => ({ application: apps[page] ?? null }) };
    }
    if (url.includes("/fill")) {
      posts.push(url);
      return fillResponse();
    }
    throw new Error(`Unexpected URL ${url}`);
  };
});

const pending = { applicationId: "id1", lookupUrl: "https://example.test/job", workspace: "w1", tabId: 1, operationId: "prep1" };
const second = { ...pending, applicationId: "id2", lookupUrl: "https://example.test/other", tabId: 2 };

test("popup closure and concurrent alarms start only one fill", async () => {
  await startFollowUp(pending);
  await advanceFollowUp();
  assert.equal(posts.length, 0);
  active = null;
  apps[pending.lookupUrl].status = "ready";
  await Promise.all([advanceFollowUp(), advanceFollowUp()]);
  assert.equal(posts.length, 1);
  assert.deepEqual(session.pendingFills, {});
});

test("an interrupted dispatch does not replay fill", async () => {
  await startFollowUp(pending);
  session.pendingFills.id1.phase = "dispatching";
  active = null;
  apps[pending.lookupUrl].status = "ready";
  await advanceFollowUp();
  assert.equal(posts.length, 0);
  assert.match(session.lastResult, /Check ResumeTailor/);
});

test("workspace changes cancel queued fill", async () => {
  await startFollowUp({ ...pending, workspace: "w2" });
  active = null;
  apps[pending.lookupUrl].status = "ready";
  const finished = await advanceFollowUp();
  assert.equal(posts.length, 0);
  assert.deepEqual(session.pendingFills, {});
  assert.match(finished[0], /Workspace changed/);
});

test("two applications wait on their own and one cancel leaves the other", async () => {
  apps[second.lookupUrl] = { id: "id2", status: "tailoring", archived: false };
  await startFollowUp(pending);
  await startFollowUp(second);
  await assert.rejects(startFollowUp(pending), /already waiting/);
  await cancelFollowUp("id1");
  assert.deepEqual(Object.keys(session.pendingFills), ["id2"]);
  active = null;
  apps[second.lookupUrl].status = "ready";
  await advanceFollowUp();
  assert.equal(posts.length, 1);
  assert.match(posts[0], /applications\/id2\/fill$/);
});

test("a retained row is continued in its tab, not started over", async () => {
  await startFollowUp(pending);
  active = null;
  apps[pending.lookupUrl].status = "awaiting_review";
  const finished = await advanceFollowUp();
  assert.equal(posts.length, 1);
  assert.match(posts[0], /\/fill\?mode=continue$/);
  assert.match(finished[0], /continued/);
});

test("a busy fill waits for the next alarm instead of giving up", async () => {
  await startFollowUp(pending);
  active = null;
  apps[pending.lookupUrl].status = "ready";
  fillResponse = () => ({ ok: false, status: 409, json: async () => ({ detail: "Busy" }) });
  assert.deepEqual(await advanceFollowUp(), []);
  assert.equal(session.pendingFills.id1.phase, "waiting");
  fillResponse = () => ({ ok: true, json: async () => ({ operation_id: "fill1" }) });
  await advanceFollowUp();
  assert.equal(posts.length, 2);
  assert.deepEqual(session.pendingFills, {});
});

test("every wait has an end: final status, stalled preparation and the time limit", async () => {
  apps[second.lookupUrl] = { id: "id2", status: "jd_fetched", archived: false };
  apps["https://example.test/third"] = { id: "id3", status: "tailoring", archived: false };
  await startFollowUp(pending);
  await startFollowUp(second);
  await startFollowUp({ ...pending, applicationId: "id3", lookupUrl: "https://example.test/third" });
  apps[pending.lookupUrl].status = "skipped";
  session.pendingFills.id2.startedAt -= 60_000;
  session.pendingFills.id3.startedAt -= FOLLOW_UP_LIMIT_MS + 1;
  active = null;
  const finished = await advanceFollowUp();
  assert.equal(posts.length, 0);
  assert.equal(finished.length, 3);
  assert.match(finished.join("\n"), /stopped: skipped/);
  assert.match(finished.join("\n"), /Preparation stopped/);
  assert.match(finished.join("\n"), /did not get ready in time/);
  assert.deepEqual(session.pendingFills, {});
});

test("an unknown status fails visibly", async () => {
  await startFollowUp(pending);
  apps[pending.lookupUrl].status = "something_new";
  const finished = await advanceFollowUp();
  assert.match(finished[0], /something new/);
  assert.deepEqual(session.pendingFills, {});
});
