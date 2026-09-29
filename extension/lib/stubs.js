// Completing a saved search card when the user opens its job (pure decisions; the
// background worker does the I/O). Once per job per page view: the content script sends
// a job only once per load, and `CompletionGuard` drops overlapping requests.

// Status text for a tracked row, as the popup and page chip show it.
export function statusLabel(app) {
  if (!app) return "";
  if (app.capture_stub) return "Needs description";
  return String(app.status || "").replaceAll("_", " ");
}

// Whether an opened job should send its description now.
export function shouldComplete({ application, jobKey, dataKey, description, minChars = 200 }) {
  if (!application?.capture_stub) return false;
  if (!jobKey || jobKey !== dataKey) return false; // the pane moved on to another job
  return (description || "").trim().length >= minChars;
}

export class CompletionGuard {
  constructor() {
    this.active = new Set();
  }

  // True when the caller may start completing ``key`` (and must call ``done``).
  begin(key) {
    if (!key || this.active.has(key)) return false;
    this.active.add(key);
    return true;
  }

  done(key) {
    this.active.delete(key);
  }
}

// Which cards to offer in the popup: each with its queue status from lookup-batch.
export function mergeCardStatus(cards, results) {
  const byUrl = new Map((results || []).map((item) => [item.url, item]));
  return cards.map((card) => {
    const found = byUrl.get(card.url);
    return {
      ...card,
      tracked: !!found?.exists,
      id: found?.id || "",
      status: found?.exists ? (found.stub ? "Needs description" : String(found.status).replaceAll("_", " ")) : "",
    };
  });
}
