import { describe, expect, it } from "vitest";
import {
  BROWSER_DEBUG_COMMANDS,
  BROWSER_TARGET_LABELS,
  defaultTarget,
  EDGE_DEBUG_COMMAND,
  EDGE_DEBUG_COMMANDS,
  detectOs,
} from "./browserCommand";

describe("EDGE_DEBUG_COMMAND", () => {
  it("keeps Windows path separators so the copied command runs", () => {
    expect(EDGE_DEBUG_COMMAND).toContain(
      String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
    );
    expect(EDGE_DEBUG_COMMAND).toContain(String.raw`$env:LOCALAPPDATA\ResumeTailorEdge`);
  });

  it("disables background throttling on every platform and browser", () => {
    for (const { command } of Object.values(BROWSER_DEBUG_COMMANDS)) {
      expect(command).toContain("--disable-background-timer-throttling");
      expect(command).toContain("--disable-renderer-backgrounding");
      expect(command).toContain("--disable-backgrounding-occluded-windows");
    }
  });

  it("never lets arbitrary web pages attach to the debugging port", () => {
    for (const { command } of Object.values(BROWSER_DEBUG_COMMANDS)) {
      expect(command).not.toContain("remote-allow-origins");
      expect(command).toContain("--remote-debugging-port=9222");
    }
  });

  it("uses dedicated profile directories for macOS browsers", () => {
    expect(BROWSER_DEBUG_COMMANDS["mac-edge"].command).toContain("ResumeTailorEdge");
    expect(BROWSER_DEBUG_COMMANDS["mac-chrome"].command).toContain("ResumeTailorChrome");
    expect(BROWSER_DEBUG_COMMANDS["mac-comet"].command).toContain("ResumeTailorComet");
  });

  it("maintains backward-compatible EDGE_DEBUG_COMMANDS map", () => {
    expect(EDGE_DEBUG_COMMANDS.windows).toEqual(BROWSER_DEBUG_COMMANDS.windows);
    expect(EDGE_DEBUG_COMMANDS.mac).toEqual(BROWSER_DEBUG_COMMANDS["mac-edge"]);
    expect(EDGE_DEBUG_COMMANDS.linux).toEqual(BROWSER_DEBUG_COMMANDS.linux);
  });

  it("labels tiles for macOS Edge, Chrome, and Comet", () => {
    expect(BROWSER_TARGET_LABELS["mac-edge"]).toBe("MacOS - Edge");
    expect(BROWSER_TARGET_LABELS["mac-chrome"]).toBe("MacOS - Chrome");
    expect(BROWSER_TARGET_LABELS["mac-comet"]).toBe("MacOS - Comet");
  });
});

describe("detectOs and defaultTarget", () => {
  it.each([
    ["MacIntel", "mac"],
    ["Win32", "windows"],
    ["Linux x86_64", "linux"],
    ["Linux armv8l Android", "windows"],
    ["", "windows"],
  ])("%s -> %s", (platform, expected) => {
    expect(detectOs(platform)).toBe(expected);
  });

  it("resolves default target from OS", () => {
    expect(defaultTarget("mac")).toBe("mac-edge");
    expect(defaultTarget("windows")).toBe("windows");
    expect(defaultTarget("linux")).toBe("linux");
  });
});
