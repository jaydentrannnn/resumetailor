// LinkedIn/Indeed content script (registered only after the user grants those sites;
// lib/boards.js). It watches which job is open and:
// - shows a small chip: "Save to ResumeTailor" or "✓ In queue · <status>";
// - asks the extension to send a saved card's description once the job's pane has
//   loaded it, once per job per page view.
// It never clicks, scrolls, navigates or fetches anything on the page.
(() => {
  if (globalThis.__resumeTailorContent) return;
  globalThis.__resumeTailorContent = true;
  const sites = globalThis.RTSites;
  const POLL_MS = 1000;
  const SETTLE_MS = 1500;
  const MAX_TRIES = 3;

  let current = null; // {key, site, since, lastText}
  const sent = new Set(); // job keys whose description was already offered this page view
  const tries = new Map();
  const dismissed = new Set();
  let host = null;
  let busy = false;

  function send(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (reply) => {
          resolve(chrome.runtime.lastError ? null : reply);
        });
      } catch {
        resolve(null); // the extension was reloaded; this page's script is orphaned
      }
    });
  }

  function chipRoot() {
    if (host?.isConnected) return host.shadowRoot;
    host = document.createElement("div");
    host.id = "resumetailor-chip";
    host.style.cssText = "all:initial;position:fixed;right:16px;bottom:16px;z-index:2147483646;";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      .chip{font:13px/1.3 system-ui,-apple-system,"Segoe UI",sans-serif;color:#fff;background:#0b0b0b;
        border:1px solid #0b0b0b;border-radius:4px;box-shadow:0 8px 24px -12px rgba(0,0,0,.18);
        display:flex;align-items:center;gap:8px;padding:6px 8px 6px 12px;max-width:min(420px,calc(100vw - 48px))}
      .chip::before{content:"";width:8px;height:8px;flex-shrink:0;background:#1f6b4a;border-radius:2px}
      .label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
      button{font:inherit;cursor:pointer;border:1px solid #3a3a38;background:#0b0b0b;color:#fff;
        border-radius:4px;padding:3px 10px;white-space:nowrap;flex-shrink:0}
      button.primary{background:#0b0b0b;border-color:#0b0b0b;color:#fff}
      button.close{border:none;padding:2px 6px;color:#d4d4d2}
      button:hover{background:#1d1d1d}
      button:focus-visible{outline:2px solid #6fbf98;outline-offset:2px}
      button:disabled{opacity:.5;cursor:default}
      @media (prefers-color-scheme: dark){
        .chip{background:#f5f5f4;color:#0b0b0b;border-color:#f5f5f4;box-shadow:0 0 0 1px #2a2a2a}
        .chip::before{background:#6fbf98}
        button{background:#f5f5f4;color:#0b0b0b;border-color:#c8c8c4}
        button.primary{background:#f5f5f4;border-color:#f5f5f4;color:#0b0b0b}
        button.close{color:#3a3a38}
        button:hover{background:#e2e2df}
        button:focus-visible{outline-color:#1f6b4a}
      }`;
    const box = document.createElement("div");
    box.className = "chip";
    box.setAttribute("role", "status");
    shadow.append(style, box);
    document.documentElement.append(host);
    return shadow;
  }

  function removeChip() {
    host?.remove();
    host = null;
  }

  function button(label, onClick, className = "") {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = label;
    if (className) element.className = className;
    element.addEventListener("click", async () => {
      if (busy) return;
      busy = true;
      element.disabled = true;
      try {
        await onClick();
      } finally {
        busy = false;
        element.disabled = false;
      }
    });
    return element;
  }

  function render(key, reply, note = "") {
    if (!reply || reply.state === "none" || !reply.chip || dismissed.has(key) || current?.key !== key) {
      removeChip();
      return;
    }
    const box = chipRoot().querySelector(".chip");
    const parts = [];
    const app = reply.application;
    const label = document.createElement("span");
    label.className = "label";
    if (reply.state === "unpaired") {
      label.textContent = "ResumeTailor: pair the extension from its popup";
      parts.push(label);
    } else if (!app) {
      label.textContent = note || "ResumeTailor";
      parts.push(label, button("Save to ResumeTailor", () => chipAction(key, "save"), "primary"));
    } else {
      label.textContent = note || `✓ In queue · ${reply.label}`;
      parts.push(label);
      if (!app.capture_stub && !["screened_out", "ready"].includes(app.status) && !app.archived) {
        parts.push(button("Tailor", () => chipAction(key, "tailor")));
      }
      parts.push(button("Open in app", () => send({ type: "chip", action: "open", id: app.link_id || app.id })));
    }
    parts.push(button("×", () => {
      dismissed.add(key);
      removeChip();
    }, "close"));
    box.replaceChildren(...parts);
    box.lastElementChild.setAttribute("aria-label", "Hide for this job");
  }

  async function chipAction(key, action) {
    const reply = await send({ type: "chip", action });
    if (!reply?.ok) {
      render(key, { state: "ok", chip: true, application: null }, reply?.error || "Could not reach ResumeTailor");
      return;
    }
    await report(true);
  }

  // Ask the extension about the open job (and to complete it if it is a saved card).
  async function report(force = false) {
    const job = current;
    if (!job) return;
    const detail = sites.readDetail(document, job.site);
    const text = detail?.description || "";
    const ready = text.length >= sites.READY_CHARS &&
      // The pane swaps content after the URL changes: wait until the text is new and stable.
      text !== job.previousText && text === job.lastText;
    job.lastText = text;
    const complete = ready && !sent.has(job.key);
    if (!complete && !force && job.reported) return;
    const reply = await send({ type: "job-view", url: location.href, key: job.key, complete });
    if (current !== job) return;
    job.reported = true;
    const value = reply?.ok ? reply.value : null;
    if (complete) {
      const failed = !reply?.ok;
      const count = (tries.get(job.key) || 0) + 1;
      tries.set(job.key, count);
      if (!failed || count >= MAX_TRIES) sent.add(job.key);
    }
    render(job.key, value, value?.completed ? "✓ Description saved to ResumeTailor" : "");
  }

  function tick() {
    const job = sites.jobFromUrl(location.href);
    if (!job) {
      if (current) removeChip();
      current = null;
      return;
    }
    if (current?.key !== job.key) {
      const previousText = current?.lastText || "";
      current = { ...job, since: Date.now(), previousText, lastText: "", reported: false };
      removeChip();
      return;
    }
    if (Date.now() - current.since < SETTLE_MS) return;
    void report();
  }

  setInterval(tick, POLL_MS);
  tick();
})();
