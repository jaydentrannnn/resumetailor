// User options (options page), kept in chrome.storage.local under one key.

export const DEFAULTS = Object.freeze({
  //: 0 = find the app on ports 8000–8010; otherwise only this loopback port.
  port: 0,
  //: What a capture from the shortcut, context menu or page chip does next.
  afterCapture: "send",
  //: The floating "Save to ResumeTailor" chip on LinkedIn/Indeed job pages.
  pageChip: true,
  //: Send a saved card's description automatically when its job is opened.
  autoComplete: true,
  //: Advanced: offer "Use this tab for Fill (relay)" (needs the debugger permission).
  relay: false,
});

const KEY = "options";
const AFTER_CAPTURE = new Set(["send", "send+tailor"]);

// A complete, valid options object from whatever was stored (unknown keys dropped).
export function normalize(raw) {
  const value = raw && typeof raw === "object" ? raw : {};
  const port = Number(value.port);
  return {
    port: Number.isInteger(port) && port >= 1024 && port <= 65535 ? port : 0,
    afterCapture: AFTER_CAPTURE.has(value.afterCapture) ? value.afterCapture : DEFAULTS.afterCapture,
    pageChip: typeof value.pageChip === "boolean" ? value.pageChip : DEFAULTS.pageChip,
    autoComplete: typeof value.autoComplete === "boolean" ? value.autoComplete : DEFAULTS.autoComplete,
    relay: typeof value.relay === "boolean" ? value.relay : DEFAULTS.relay,
  };
}

// Parse the options page's port field: "" means automatic. Throws on anything else.
export function parsePort(text) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return 0;
  const port = Number(trimmed);
  if (!/^\d+$/.test(trimmed) || port < 1024 || port > 65535) {
    throw new Error("Enter a port between 1024 and 65535, or leave it empty.");
  }
  return port;
}

export async function getOptions() {
  const stored = await chrome.storage.local.get(KEY);
  return normalize(stored[KEY]);
}

export async function setOptions(patch) {
  const next = normalize({ ...(await getOptions()), ...patch });
  await chrome.storage.local.set({ [KEY]: next });
  return next;
}
