import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { capture, findPort, request } from "../lib/api.js";

let local;
let session;
let calls;

beforeEach(() => {
  local = {};
  session = {};
  calls = [];
  globalThis.chrome = {
    storage: {
      local: {
        get: async (key) => ({ [key]: local[key] }),
        set: async (value) => Object.assign(local, value),
        remove: async (key) => { delete local[key]; },
      },
      session: { remove: async (key) => { delete session[key]; } },
    },
  };
});

test("finds the lowest valid app and reuses its port", async () => {
  globalThis.fetch = async (url) => {
    calls.push(url);
    const port = new URL(url).port;
    return { ok: true, json: async () => ({ app: port === "8002" ? "resumetailor" : "other" }) };
  };
  assert.equal(await findPort(), 8002);
  assert.equal(local.port, 8002);
  calls = [];
  assert.equal(await findPort(), 8002);
  assert.equal(calls.length, 1);
});

test("revocation clears credential and queued fill", async () => {
  local = { port: 8000, token: "secret" };
  session.pendingFill = { applicationId: "a" };
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/api/health")) return { ok: true, json: async () => ({ app: "resumetailor" }) };
    assert.equal(options.headers["X-RT-Extension"], "secret");
    return { ok: false, status: 401, json: async () => ({ error: "extension_auth" }) };
  };
  await assert.rejects(() => request("/api/extension/status"), /Pair again/);
  assert.equal(local.token, undefined);
  assert.equal(session.pendingFill, undefined);
});

test("capture sends one JSON request with the paired token", async () => {
  local = { port: 8000, token: "secret" };
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/api/health")) return { ok: true, json: async () => ({ app: "resumetailor" }) };
    calls.push({ url, options });
    return { ok: true, json: async () => ({ result: "created" }) };
  };
  assert.equal((await capture({ url: "https://example.test/job", jd_text: "A".repeat(200) })).result, "created");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers["X-RT-Extension"], "secret");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
});
