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

export const EDGE_DEBUG_COMMANDS: Record<DesktopOs, { shell: string; command: string }> = {
  windows: {
    shell: "PowerShell",
    command: String.raw`& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\ResumeTailorEdge"`,
  },
  mac: {
    shell: "Terminal",
    command: String.raw`"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/ResumeTailorEdge"`,
  },
  linux: {
    shell: "a terminal",
    command: String.raw`microsoft-edge --remote-debugging-port=9222 --user-data-dir="$HOME/.config/ResumeTailorEdge"`,
  },
};

/** Kept for callers that only ever showed the Windows command. */
export const EDGE_DEBUG_COMMAND = EDGE_DEBUG_COMMANDS.windows.command;

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
