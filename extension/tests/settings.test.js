import { beforeEach, test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULTS, getOptions, normalize, parsePort, setOptions } from "../lib/settings.js";
import { findPort } from "../lib/api.js";

let local;

beforeEach(() => {
  local = {};
  globalThis.chrome = {
    storage: {
      local: {
        get: async (key) => ({ [key]: local[key] }),
        set: async (value) => Object.assign(local, value),
        remove: async (key) => { delete local[key]; },
      },
    },
  };
});

test("stored options are normalised", () => {
  assert.deepEqual(normalize(undefined), { ...DEFAULTS });
  assert.deepEqual(
    normalize({ port: "8123", afterCapture: "send+tailor", pageChip: false, relay: "yes", extra: 1 }),
    { port: 8123, afterCapture: "send+tailor", pageChip: false, autoComplete: true, relay: false },
  );
  assert.equal(normalize({ port: 80 }).port, 0);
  assert.equal(normalize({ afterCapture: "submit" }).afterCapture, "send");
});

test("the port field accepts empty or a valid port", () => {
  assert.equal(parsePort(""), 0);
  assert.equal(parsePort(" 8123 "), 8123);
  assert.throws(() => parsePort("80"), /1024/);
  assert.throws(() => parsePort("8000x"), /port/);
});

test("options round-trip through storage", async () => {
  assert.deepEqual(await getOptions(), { ...DEFAULTS });
  await setOptions({ pageChip: false });
  await setOptions({ afterCapture: "send+tailor" });
  assert.deepEqual(await getOptions(), { ...DEFAULTS, pageChip: false, afterCapture: "send+tailor" });
  assert.equal(local.options.pageChip, false);
});

test("a port override is the only port probed", async () => {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url).port);
    return { ok: true, json: async () => ({ app: "resumetailor" }) };
  };
  await setOptions({ port: 8123 });
  assert.equal(await findPort(), 8123);
  assert.deepEqual(calls, ["8123"]);
  globalThis.fetch = async () => { throw new Error("refused"); };
  await assert.rejects(findPort, (error) => error.code === "app_not_running" && /8123/.test(error.message));
});
