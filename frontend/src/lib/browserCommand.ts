// Edge, not Chrome: Chrome refuses to open its remote-debugging port whenever any
// other Chrome window (any profile) is already running under this account, which
// would mean closing the user's normal browsing session every time. Edge is a
// separate binary/process, so it can run this debug profile in the background
// without touching Chrome at all.
//
// No `--remote-allow-origins=*`: that flag lets any web page open in the browser
// connect to the DevTools socket and drive the logged-in job-site sessions.
// Playwright's CDP client sends no Origin header, so it connects without it.

export type DesktopOs = "windows" | "mac" | "linux";

export type BrowserTarget = "windows" | "mac-edge" | "mac-chrome" | "mac-comet" | "linux";

export interface BrowserDebugConfig {
  browser: string;
  shell: string;
  command: string;
}

export const BROWSER_DEBUG_COMMANDS: Record<BrowserTarget, BrowserDebugConfig> = {
  windows: {
    browser: "Edge",
    shell: "PowerShell",
    command: String.raw`& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --user-data-dir="$env:LOCALAPPDATA\ResumeTailorEdge"`,
  },
  "mac-edge": {
    browser: "Edge",
    shell: "Terminal",
    command: String.raw`"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" --remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --user-data-dir="$HOME/Library/Application Support/ResumeTailorEdge"`,
  },
  "mac-chrome": {
    browser: "Chrome",
    shell: "Terminal",
    command: String.raw`"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --user-data-dir="$HOME/Library/Application Support/ResumeTailorChrome"`,
  },
  "mac-comet": {
    browser: "Comet",
    shell: "Terminal",
    command: String.raw`"/Applications/Comet.app/Contents/MacOS/Comet" --remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --user-data-dir="$HOME/Library/Application Support/ResumeTailorComet"`,
  },
  linux: {
    browser: "Edge",
    shell: "a terminal",
    command: String.raw`microsoft-edge --remote-debugging-port=9222 --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --user-data-dir="$HOME/.config/ResumeTailorEdge"`,
  },
};

export const BROWSER_TARGET_LABELS: Record<BrowserTarget, string> = {
  windows: "Windows",
  "mac-edge": "MacOS - Edge",
  "mac-chrome": "MacOS - Chrome",
  "mac-comet": "MacOS - Comet",
  linux: "Linux",
};

/** Kept for backwards compatibility. */
export const EDGE_DEBUG_COMMANDS: Record<DesktopOs, { shell: string; command: string }> = {
  windows: BROWSER_DEBUG_COMMANDS.windows,
  mac: BROWSER_DEBUG_COMMANDS["mac-edge"],
  linux: BROWSER_DEBUG_COMMANDS.linux,
};

/** Kept for callers that only ever showed the Windows command. */
export const EDGE_DEBUG_COMMAND = BROWSER_DEBUG_COMMANDS.windows.command;

/** Best guess at the viewer's OS from the browser; Windows when unsure. */
export function detectOs(
  platform: string = typeof navigator === "undefined"
    ? ""
    : navigator.platform || navigator.userAgent,
): DesktopOs {
  const value = platform.toLowerCase();
  if (value.includes("mac")) return "mac";
  if (value.includes("linux") && !value.includes("android")) return "linux";
  return "windows";
}

/** Resolves initial browser target based on the detected OS. */
export function defaultTarget(os: DesktopOs = detectOs()): BrowserTarget {
  if (os === "mac") return "mac-edge";
  if (os === "linux") return "linux";
  return "windows";
}
