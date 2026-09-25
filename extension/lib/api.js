const FIRST_PORT = 8000;
const LAST_PORT = 8010;
const PROBE_MS = 1000;

export class ExtensionApiError extends Error {
  constructor(message, status = 0, code = "") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function health(port) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_MS);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/health`, {
      signal: controller.signal,
      credentials: "omit",
      redirect: "error",
    });
    return response.ok && (await response.json()).app === "resumetailor";
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export async function findPort() {
  const saved = await chrome.storage.local.get("port");
  if (Number.isInteger(saved.port) && saved.port >= FIRST_PORT && saved.port <= LAST_PORT) {
    if (await health(saved.port)) return saved.port;
  }
  // Three probes at a time keeps discovery bounded and selects the lowest valid port.
  for (let first = FIRST_PORT; first <= LAST_PORT; first += 3) {
    const ports = [first, first + 1, first + 2].filter((port) => port <= LAST_PORT);
    const found = await Promise.all(ports.map(health));
    const index = found.indexOf(true);
    if (index >= 0) {
      await chrome.storage.local.set({ port: ports[index] });
      return ports[index];
    }
  }
  await chrome.storage.local.remove("port");
  throw new ExtensionApiError("Start ResumeTailor first.");
}

function detailText(body, fallback) {
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) {
    return body.detail.map((item) => item.msg || String(item)).join("; ");
  }
  return fallback;
}

export async function request(path, { method = "GET", body, paired = true } = {}) {
  const port = await findPort();
  const saved = await chrome.storage.local.get("token");
  if (paired && !saved.token) throw new ExtensionApiError("Pair again.", 401, "extension_auth");
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (paired) headers["X-RT-Extension"] = saved.token;
  let response;
  try {
    response = await fetch(`http://127.0.0.1:${port}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      redirect: "error",
    });
  } catch {
    throw new ExtensionApiError("Cannot reach ResumeTailor. Check that it is running.");
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    // A 204 or non-JSON error has no structured detail.
  }
  if (!response.ok) {
    if (response.status === 401 && payload.error === "extension_auth") {
      await chrome.storage.local.remove("token");
      await chrome.storage.session.remove("pendingFill");
      throw new ExtensionApiError("Pair again.", 401, "extension_auth");
    }
    throw new ExtensionApiError(detailText(payload, `ResumeTailor returned ${response.status}.`), response.status, payload.error);
  }
  return payload;
}

export async function pair(code, label) {
  const result = await request("/api/extension/pair/complete", {
    method: "POST",
    body: { code, label },
    paired: false,
  });
  await chrome.storage.local.set({ token: result.token });
  return result;
}

export const status = () => request("/api/extension/status");
export const lookup = (url) => request(`/api/extension/lookup?url=${encodeURIComponent(url)}`);
export const capture = (data) => request("/api/extension/capture", { method: "POST", body: data });
export const operation = (id, action) =>
  request(`/api/extension/applications/${encodeURIComponent(id)}/${action}`, { method: "POST" });
