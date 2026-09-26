import { describe, expect, it } from "vitest";
import type { UpdateStatus } from "../api";
import { sinceLabel, updateChipLabel, updateChipVisible, updateStatusLine } from "./updateStatus";

const base: UpdateStatus = {
  supported: true,
  current: "0.1.1",
  state: "idle",
  available: null,
  pct: null,
  last_checked: null,
  error: null,
  waiting_for: null,
  backup: null,
};
const found = { version: "0.2.0", notes: "Faster fills", date: "" };

describe("updateStatusLine", () => {
  it("describes each state", () => {
    expect(updateStatusLine({ ...base, state: "available", available: found })).toBe(
      "Version 0.2.0 is available.",
    );
    expect(updateStatusLine({ ...base, state: "downloading", available: found, pct: 45 })).toBe(
      "Downloading version 0.2.0… 45%",
    );
    expect(
      updateStatusLine({
        ...base,
        state: "waiting",
        available: found,
        waiting_for: "a tailoring run",
      }),
    ).toBe("Version 0.2.0 is downloaded. It installs when a tailoring run finishes.");
    expect(updateStatusLine({ ...base, state: "error", error: "signature mismatch" })).toBe(
      "signature mismatch",
    );
    expect(updateStatusLine(base)).toMatch(/Not checked yet/);
  });

  it("says when it last checked", () => {
    const now = Date.parse("2026-09-26T12:00:00Z");
    const status = { ...base, state: "up_to_date" as const, last_checked: "2026-09-26T10:00:00Z" };
    expect(updateStatusLine(status, now)).toBe("Up to date · checked 2 h ago");
  });
});

describe("sinceLabel", () => {
  const now = Date.parse("2026-09-26T12:00:00Z");
  it("rounds to minutes, hours and days", () => {
    expect(sinceLabel("2026-09-26T11:59:50Z", now)).toBe("just now");
    expect(sinceLabel("2026-09-26T11:55:00Z", now)).toBe("5 min ago");
    expect(sinceLabel("2026-09-25T12:00:00Z", now)).toBe("1 day ago");
    expect(sinceLabel("2026-09-23T12:00:00Z", now)).toBe("3 days ago");
    expect(sinceLabel("not a date", now)).toBe("");
  });
});

describe("update chip", () => {
  it("shows only in the desktop app, for an update on offer or on its way", () => {
    expect(updateChipVisible(null)).toBe(false);
    expect(updateChipVisible({ ...base, state: "available" })).toBe(true);
    expect(updateChipVisible({ ...base, state: "waiting" })).toBe(true);
    expect(updateChipVisible({ ...base, state: "up_to_date" })).toBe(false);
    expect(updateChipVisible({ ...base, state: "error" })).toBe(false);
    expect(updateChipVisible({ ...base, supported: false, state: "available" })).toBe(false);
  });

  it("labels an offer differently from an install in progress", () => {
    expect(updateChipLabel({ ...base, state: "available" })).toBe("Update available");
    expect(updateChipLabel({ ...base, state: "downloading" })).toBe("Updating…");
  });
});
