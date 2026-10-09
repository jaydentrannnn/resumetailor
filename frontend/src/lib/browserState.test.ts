import { describe, expect, it } from "vitest";
import type { BrowserStatus } from "../api";
import { browserView, resolveBrowser } from "./browserState";

const status = (fields: Partial<BrowserStatus> = {}): BrowserStatus => ({
  reachable: false,
  browser: "",
  user_agent: "",
  error: "",
  cdp_url: "http://127.0.0.1:9222",
  state: "idle",
  reason: "",
  can_launch: true,
  docker: false,
  installed: { edge: true, chrome: true, comet: false },
  selected: null,
  resolved: "edge",
  ...fields,
});

describe("resolveBrowser", () => {
  it("keeps an installed choice and refuses an uninstalled one", () => {
    expect(resolveBrowser("chrome", { chrome: true })).toBe("chrome");
    expect(resolveBrowser("comet", { edge: true })).toBeNull();
  });

  it("picks the first installed in Edge, Chrome, Comet order when automatic", () => {
    expect(resolveBrowser(null, { chrome: true, comet: true })).toBe("chrome");
    expect(resolveBrowser(null, {})).toBeNull();
  });
});

describe("browserView", () => {
  it("is unknown (unavailable, no reason) before the first status", () => {
    expect(browserView(null, null)).toEqual({ state: "unavailable", reason: "", resolved: null });
  });

  it("is ready whenever the debug port answers", () => {
    expect(browserView(status({ reachable: true }), "comet").state).toBe("ready");
  });

  it("is idle when the app can start an installed browser", () => {
    expect(browserView(status(), "chrome")).toEqual({ state: "idle", reason: "", resolved: "chrome" });
  });

  it("names an uninstalled choice before the autosave reaches the server", () => {
    const view = browserView(status(), "comet");
    expect(view.state).toBe("unavailable");
    expect(view.reason).toBe("Comet isn't installed on this computer.");
  });

  it("keeps the server's reason for the same browser, drops it for a new choice", () => {
    const busy = status({ state: "unavailable", reason: "Port 9222 is used", resolved: "edge" });
    expect(browserView(busy, null).reason).toBe("Port 9222 is used");
    expect(browserView(busy, "chrome").state).toBe("idle");
  });

  it("is unavailable with the probe error when the app can't launch (Docker)", () => {
    const docker = status({ can_launch: false, docker: true, error: "connection refused" });
    expect(browserView(docker, null)).toMatchObject({
      state: "unavailable",
      reason: "connection refused",
    });
  });
});
