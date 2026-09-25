import { describe, expect, it } from "vitest";
import { EDGE_DEBUG_COMMAND, EDGE_DEBUG_COMMANDS, detectOs } from "./browserCommand";

describe("EDGE_DEBUG_COMMAND", () => {
  it("keeps Windows path separators so the copied command runs", () => {
    expect(EDGE_DEBUG_COMMAND).toContain(
      String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,
    );
    expect(EDGE_DEBUG_COMMAND).toContain(String.raw`$env:LOCALAPPDATA\ResumeTailorEdge`);
  });

  it("never lets arbitrary web pages attach to the debugging port", () => {
    for (const { command } of Object.values(EDGE_DEBUG_COMMANDS)) {
      expect(command).not.toContain("remote-allow-origins");
      expect(command).toContain("--remote-debugging-port=9222");
    }
  });
});

describe("detectOs", () => {
  it.each([
    ["MacIntel", "mac"],
    ["Win32", "windows"],
    ["Linux x86_64", "linux"],
    ["Linux armv8l Android", "windows"],
    ["", "windows"],
  ])("%s -> %s", (platform, expected) => {
    expect(detectOs(platform)).toBe(expected);
  });
});
