// Relay the selected tab's CDP messages to the loopback application endpoint.
// `debugger` is an optional permission (requested when the relay is turned on in the
// options page), so `chrome.debugger` may not exist when this module loads.
let socket = null;
let tabId = null;
let keepalive = null;
let listening = false;

function send(message) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function listen() {
  if (listening) return;
  listening = true;
  chrome.debugger.onEvent.addListener((source, method, params) => {
    if (source.tabId !== tabId) return;
    send({ type: "event", method, params, sessionId: source.sessionId || null });
  });
  chrome.debugger.onDetach.addListener((source, reason) => {
    if (source.tabId !== tabId) return;
    send({ type: "detached", reason });
    socket?.close();
    socket = null;
    tabId = null;
    if (keepalive) clearInterval(keepalive);
  });
}

export async function relayAllowed() {
  return chrome.permissions.contains({ permissions: ["debugger"] });
}

export async function connectRelay(tab) {
  if (!tab?.id || !/^https?:\/\//.test(tab.url || "")) throw new Error("Choose a job tab first.");
  if (!(await relayAllowed()) || !chrome.debugger) {
    throw new Error("Turn on the relay in the extension options first.");
  }
  listen();
  if (socket?.readyState === WebSocket.OPEN) throw new Error("Relay is already connected.");
  const { token } = await chrome.storage.local.get("token");
  if (!token) throw new Error("Pair again before connecting the relay.");
  await chrome.debugger.attach({ tabId: tab.id }, "1.3");
  tabId = tab.id;
  try {
    const info = await chrome.debugger.sendCommand({ tabId }, "Target.getTargetInfo");
    socket = new WebSocket("ws://127.0.0.1:8011/extension");
    await new Promise((resolve, reject) => {
      socket.addEventListener("open", resolve, { once: true });
      socket.addEventListener("error", () => reject(new Error("Start the relay on port 8011 first.")), { once: true });
    });
    send({ type: "hello", token, target: info.targetInfo });
    socket.addEventListener("message", async (event) => {
      let message;
      try { message = JSON.parse(event.data); } catch { return; }
      if (message.type !== "command") return;
      try {
        const target = message.sessionId ? { tabId, sessionId: message.sessionId } : { tabId };
        const result = await chrome.debugger.sendCommand(target, message.method, message.params || {});
        send({ type: "response", id: message.id, result: result || {} });
      } catch (error) {
        send({ type: "response", id: message.id, error: error.message });
      }
    });
    socket.addEventListener("close", () => {
      if (keepalive) clearInterval(keepalive);
      keepalive = null;
      const attachedTab = tabId;
      socket = null;
      tabId = null;
      if (attachedTab !== null) void chrome.debugger.detach({ tabId: attachedTab }).catch(() => {});
    }, { once: true });
    keepalive = setInterval(() => send({ type: "ping" }), 20_000);
    return { message: "Relay connected to this tab." };
  } catch (error) {
    await chrome.debugger.detach({ tabId }).catch(() => {});
    tabId = null;
    throw error;
  }
}
