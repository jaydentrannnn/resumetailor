import { describe, expect, it } from "vitest";
import { EDGE_DEBUG_COMMAND } from "./browserCommand";

describe("EDGE_DEBUG_COMMAND", () => {
  it("keeps Windows path separators so the copied command runs", () => {
    expect(EDGE_DEBUG_COMMAND).toContain(String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`);
    expect(EDGE_DEBUG_COMMAND).toContain(String.raw`$env:LOCALAPPDATA\ResumeTailorEdge`);
  });
});
