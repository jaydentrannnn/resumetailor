// The Fill relay: one socket to the loopback relay (`cdp_relay.py`) and the tabs the app
// opened through it. The app drives only tabs it asked for here (`createTab`, opened in
// the background), each under its own debugger session, so Fill, a posting fetch and the
// tab watcher work side by side and never touch the student's own tabs (audit #27, #38).
// `debugger` is an optional permission (requested when the relay is turned on in the
// options page), so `chrome.debugger` may not exist when this module loads.
const RELAY_URL = "ws://127.0.0.1:8011/extension";
/** Session-storage key: the app's tab ids, attached again after the relay restarts. */
const KEY = "relayTabs";

let socket = null;
let keepalive = null;
let listening = false;
/** tabId -> CDP target id, for every tab the app opened that the debugger is on. */
const tabs = new Map();

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

async function remember() {
  await chrome.storage.session.set({ [KEY]: [...tabs.keys()] });
}

function listen() {
  if (listening) return;
  listening = true;
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (!tabs.has(source.tabId)) return;
    send({ type: "event", tabId: source.tabId, method, params, sessionId: source.sessionId || null });
  });
  chrome.debugger.onDetach.addListener((source, reason) => {
    // The tab closed, or DevTools took it over: the app stops driving it.
    if (!tabs.has(source.tabId)) return;
    tabs.delete(source.tabId);
    void remember();
    send({ type: "detached", tabId: source.tabId, reason });
  });
}

async function attach(tabId) {
  await chrome.debugger.attach({ tabId }, "1.3");
  const { targetInfo } = await chrome.debugger.sendCommand({ tabId }, "Target.getTargetInfo");
  tabs.set(tabId, targetInfo.targetId);
  await remember();
  return targetInfo;
}

async function createTab(url) {
  const tab = await chrome.tabs.create({ url: url || "about:blank", active: false });
  try {
    return { tabId: tab.id, target: await attach(tab.id) };
  } catch (error) {
    await chrome.tabs.remove(tab.id).catch(() => {});
    throw error;
  }
}

async function closeTab(tabId) {
  if (!tabs.has(tabId)) throw new Error("Only a tab the app opened can be closed.");
  await chrome.tabs.remove(tabId);
  return {};
}

async function listTabs() {
  const rows = [];
  for (const tabId of tabs.keys()) {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (tab) rows.push({ tabId, url: tab.url || "", title: tab.title || "" });
  }
  return { tabs: rows };
}

async function handle(message) {
  switch (message.type) {
    case "command": {
      if (!tabs.has(message.tabId)) throw new Error("That tab is not attached to the relay.");
      const target = message.sessionId
        ? { tabId: message.tabId, sessionId: message.sessionId }
        : { tabId: message.tabId };
      return (await chrome.debugger.sendCommand(target, message.method, message.params || {})) || {};
    }
    case "createTab": return createTab(message.url);
    case "closeTab": return closeTab(message.tabId);
    case "listTabs": return listTabs();
    default: throw new Error(`Unknown relay request: ${message.type}`);
  }
}

/** Attach again the tabs the app opened before the relay (or this worker) restarted. */
async function readopt() {
  const { [KEY]: kept = [] } = await chrome.storage.session.get(KEY);
  for (const tabId of kept) {
    if (!(await chrome.tabs.get(tabId).catch(() => null))) continue;
    try {
      send({ type: "attached", tabId, target: await attach(tabId) });
    } catch {
      // DevTools or another debugger has it now: the tab is the student's.
    }
  }
  await remember();
}

export async function relayAllowed() {
  return chrome.permissions.contains({ permissions: ["debugger"] });
}

export function relayState() {
  return { connected: socket?.readyState === WebSocket.OPEN, tabs: tabs.size };
}

export async function connectRelay() {
  if (!(await relayAllowed()) || !chrome.debugger) {
    throw new Error("Turn on the relay in the extension options first.");
  }
  listen();
  if (socket?.readyState === WebSocket.OPEN) return { message: "The Fill relay is connected." };
  const { token } = await chrome.storage.local.get("token");
  if (!token) throw new Error("Pair again before connecting the relay.");
  const next = new WebSocket(RELAY_URL);
  await new Promise((resolve, reject) => {
    next.addEventListener("open", resolve, { once: true });
    next.addEventListener("error", () => reject(new Error("Start the relay on port 8011 first.")), { once: true });
  });
  socket = next;
  send({ type: "hello", token });
  next.addEventListener("message", async (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (!message.id) return;
    try {
      send({ type: "response", id: message.id, result: await handle(message) });
    } catch (error) {
      send({ type: "response", id: message.id, error: error.message });
    }
  });
  next.addEventListener("close", () => {
    if (keepalive) clearInterval(keepalive);
    keepalive = null;
    if (socket === next) socket = null;
    // The tabs stay open; their ids stay stored so the next connection attaches them again.
    const attached = [...tabs.keys()];
    tabs.clear();
    for (const tabId of attached) void chrome.debugger.detach({ tabId }).catch(() => {});
  }, { once: true });
  keepalive = setInterval(() => send({ type: "ping" }), 20_000);
  await readopt();
  return { message: "Fill relay connected. Fill opens its own tabs in this browser." };
}
