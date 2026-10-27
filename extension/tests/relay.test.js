import { after, beforeEach, test } from "node:test";
import assert from "node:assert/strict";

// One fake socket per connectRelay; the relay side is played by the test.
class FakeSocket {
  static OPEN = 1;
  static last = null;
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.listeners = {};
    FakeSocket.last = this;
    queueMicrotask(() => { this.readyState = 1; this.emit("open"); });
  }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  emit(type, event = {}) { for (const listener of this.listeners[type] || []) listener(event); }
  send(raw) { this.sent.push(JSON.parse(raw)); }
  close() { this.readyState = 3; this.emit("close"); }
  /** The relay asks for something; resolves to the extension's response. */
  async ask(message) {
    this.emit("message", { data: JSON.stringify(message) });
    const reply = () => this.sent.find((m) => m.type === "response" && m.id === message.id);
    for (let i = 0; i < 50 && !reply(); i += 1) await new Promise((r) => setTimeout(r, 0));
    return reply();
  }
}

let session;
let openTabs;
let attached;
let commands;
let nextTab;
// The module adds its debugger listeners once, like the worker: keep them across tests.
const events = [];
const detaches = [];

beforeEach(() => {
  session = {};
  openTabs = new Map([[1, { id: 1, url: "https://mail.example/inbox", title: "Mine" }]]);
  attached = new Set();
  commands = [];
  nextTab = 10;
  globalThis.WebSocket = FakeSocket;
  globalThis.chrome = {
    permissions: { contains: async () => true },
    storage: {
      local: { get: async () => ({ token: "secret" }) },
      session: {
        get: async (key) => ({ [key]: session[key] }),
        set: async (value) => Object.assign(session, value),
      },
    },
    tabs: {
      create: async ({ url, active }) => {
        assert.equal(active, false);
        const tab = { id: nextTab++, url, title: "" };
        openTabs.set(tab.id, tab);
        return tab;
      },
      get: async (tabId) => {
        if (!openTabs.has(tabId)) throw new Error("No tab");
        return openTabs.get(tabId);
      },
      remove: async (tabId) => {
        openTabs.delete(tabId);
        if (attached.delete(tabId)) for (const listener of detaches) listener({ tabId }, "target_closed");
      },
    },
    debugger: {
      attach: async ({ tabId }) => { attached.add(tabId); },
      detach: async ({ tabId }) => { attached.delete(tabId); },
      sendCommand: async (target, method) => {
        commands.push({ target, method });
        if (method === "Target.getTargetInfo") return { targetInfo: { targetId: `T${target.tabId}`, type: "page" } };
        return { ok: true };
      },
      onEvent: { addListener: (listener) => events.push(listener) },
      onDetach: { addListener: (listener) => detaches.push(listener) },
    },
  };
});

// One module instance across tests, like the worker; each test starts disconnected.
const relay = await import("../lib/relay.js");

// Closing stops the keepalive timer, which would otherwise hold the test process open.
after(() => FakeSocket.last?.close());

async function connect() {
  FakeSocket.last?.close();
  await relay.connectRelay();
  return FakeSocket.last;
}

test("connecting says hello with the token and attaches no tab of the student's", async () => {
  const socket = await connect();
  assert.equal(socket.url, "ws://127.0.0.1:8011/extension");
  assert.deepEqual(socket.sent[0], { type: "hello", token: "secret" });
  assert.equal(attached.size, 0);
  assert.deepEqual(relay.relayState(), { connected: true, tabs: 0 });
});

test("the app's tabs open in the background and only they take commands", async () => {
  const socket = await connect();
  const created = await socket.ask({ type: "createTab", id: 1, url: "about:blank" });
  assert.deepEqual(created.result, { tabId: 10, target: { targetId: "T10", type: "page" } });
  assert.ok(attached.has(10));
  const ok = await socket.ask({ type: "command", id: 2, tabId: 10, method: "Page.enable", params: {} });
  assert.deepEqual(ok.result, { ok: true });
  const child = await socket.ask({ type: "command", id: 3, tabId: 10, sessionId: "S1", method: "Runtime.enable" });
  assert.deepEqual(commands.at(-1).target, { tabId: 10, sessionId: "S1" });
  assert.ok(child.result);
  const refused = await socket.ask({ type: "command", id: 4, tabId: 1, method: "Page.navigate" });
  assert.match(refused.error, /not attached/);
  const closeMine = await socket.ask({ type: "closeTab", id: 5, tabId: 1 });
  assert.match(closeMine.error, /Only a tab the app opened/);
  assert.ok(openTabs.has(1));
});

test("events carry their tab, and a closed tab is reported once", async () => {
  const socket = await connect();
  await socket.ask({ type: "createTab", id: 1, url: "" });
  for (const listener of events) listener({ tabId: 10 }, "Page.loadEventFired", { timestamp: 1 });
  for (const listener of events) listener({ tabId: 1 }, "Page.loadEventFired", {});
  const forwarded = socket.sent.filter((m) => m.type === "event");
  assert.deepEqual(forwarded, [{ type: "event", tabId: 10, method: "Page.loadEventFired", params: { timestamp: 1 }, sessionId: null }]);
  const closed = await socket.ask({ type: "closeTab", id: 2, tabId: 10 });
  assert.deepEqual(closed.result, {});
  assert.deepEqual(socket.sent.filter((m) => m.type === "detached").map((m) => m.tabId), [10]);
  assert.deepEqual(relay.relayState().tabs, 0);
});

test("a reconnect attaches the app's open tabs again and lists them", async () => {
  let socket = await connect();
  await socket.ask({ type: "createTab", id: 1, url: "" });
  await socket.ask({ type: "createTab", id: 2, url: "" });
  openTabs.delete(11); // closed while the relay was away
  socket.close();
  assert.equal(attached.size, 0);
  socket = await connect();
  assert.deepEqual(socket.sent.filter((m) => m.type === "attached").map((m) => m.tabId), [10]);
  openTabs.get(10).url = "https://jobs.example/apply";
  const listed = await socket.ask({ type: "listTabs", id: 3 });
  assert.deepEqual(listed.result, { tabs: [{ tabId: 10, url: "https://jobs.example/apply", title: "" }] });
  assert.deepEqual(session.relayTabs, [10]);
});
