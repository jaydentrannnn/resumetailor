import { test } from "node:test";
import assert from "node:assert/strict";
import { CompletionGuard, mergeCardStatus, shouldComplete, statusLabel } from "../lib/stubs.js";

const stub = { id: "linkedin:jobs:1", capture_stub: true, status: "discovered" };
const long = "Build models. ".repeat(20);

test("a saved card completes only with its own, loaded description", () => {
  const base = { application: stub, jobKey: "linkedin:jobs:1", dataKey: "linkedin:jobs:1", description: long };
  assert.equal(shouldComplete(base), true);
  assert.equal(shouldComplete({ ...base, application: { ...stub, capture_stub: false } }), false);
  assert.equal(shouldComplete({ ...base, application: null }), false);
  // The pane moved to another job between the request and the extraction.
  assert.equal(shouldComplete({ ...base, dataKey: "linkedin:jobs:2" }), false);
  assert.equal(shouldComplete({ ...base, description: "Loading…" }), false);
});

test("overlapping completions of one job are dropped", () => {
  const guard = new CompletionGuard();
  assert.equal(guard.begin("linkedin:jobs:1"), true);
  assert.equal(guard.begin("linkedin:jobs:1"), false);
  assert.equal(guard.begin("indeed:jobs:a"), true);
  guard.done("linkedin:jobs:1");
  assert.equal(guard.begin("linkedin:jobs:1"), true);
  assert.equal(guard.begin(""), false);
});

test("cards carry their queue status", () => {
  const cards = [{ url: "u1" }, { url: "u2" }, { url: "u3" }];
  const merged = mergeCardStatus(cards, [
    { url: "u1", exists: true, id: "a", status: "discovered", stub: true },
    { url: "u2", exists: true, id: "b", status: "jd_fetched", stub: false },
    { url: "u3", exists: false },
  ]);
  assert.deepEqual(merged.map((card) => [card.tracked, card.status]), [
    [true, "Needs description"], [true, "jd fetched"], [false, ""],
  ]);
  assert.equal(statusLabel(stub), "Needs description");
  assert.equal(statusLabel({ status: "screened_out" }), "screened out");
  assert.equal(statusLabel(null), "");
});
