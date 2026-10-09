import type { BrowserId, BrowserStatus } from "../api";

// The app starts the chosen browser itself when Fill or a job fetch needs it
// (`apply/driver/browser_launch.py`), so there is no launch command to copy any more.
// Firefox is not offered: it no longer speaks the Chrome DevTools Protocol.

export const BROWSERS: { id: BrowserId; label: string }[] = [
  { id: "edge", label: "Edge" },
  { id: "chrome", label: "Chrome" },
  { id: "comet", label: "Comet" },
];

/** Picked in this order when the user has not chosen one (the backend's `AUTO_ORDER`). */
const AUTO_ORDER: BrowserId[] = ["edge", "chrome", "comet"];

export const browserLabel = (id: BrowserId) => BROWSERS.find((b) => b.id === id)?.label ?? id;

/** The browser the app would start: the chosen one when installed, else the first installed. */
export function resolveBrowser(
  selected: BrowserId | null,
  installed: Partial<Record<BrowserId, boolean>>,
): BrowserId | null {
  if (selected) return installed[selected] ? selected : null;
  return AUTO_ORDER.find((id) => installed[id]) ?? null;
}

export type BrowserView = {
  state: BrowserStatus["state"];
  reason: string;
  resolved: BrowserId | null;
};

/**
 * What the chip says, for the selection on screen. The backend answers for the saved
 * selection, so a just-changed choice is re-derived here from `installed` rather than
 * waiting for the autosave and another status call.
 */
export function browserView(status: BrowserStatus | null, selected: BrowserId | null): BrowserView {
  if (!status) return { state: "unavailable", reason: "", resolved: null };
  const resolved = resolveBrowser(selected, status.installed);
  if (status.reachable) return { state: "ready", reason: "", resolved };
  if (!status.can_launch)
    return { state: "unavailable", reason: status.reason || status.error, resolved };
  if (!resolved)
    return {
      state: "unavailable",
      reason: selected
        ? `${browserLabel(selected)} isn't installed on this computer.`
        : "No supported browser (Edge, Chrome or Comet) is installed.",
      resolved,
    };
  if (status.state === "unavailable" && status.resolved === resolved)
    return { state: "unavailable", reason: status.reason, resolved };
  return { state: "idle", reason: "", resolved };
}

export const CHIP_LABEL: Record<BrowserStatus["state"], string> = {
  ready: "Browser ready",
  idle: "Launches when needed",
  unavailable: "Browser not available",
};
