import { describe, expect, it } from "vitest";
import { canContinueFill, isTerminalRow, retryLabel, retryShortLabel } from "./applicationRows";

describe("isTerminalRow", () => {
  it("trusts the server's terminal_application reason for every closed status", () => {
    // skipped / interview / ghosted were missing from the old client-side copy.
    for (const reasons of [["terminal_application"], ["terminal_application", "missing_tailor_job"]]) {
      expect(isTerminalRow({ preparation_reasons: reasons })).toBe(true);
    }
  });

  it("is false for open rows and rows without reasons", () => {
    expect(isTerminalRow({ preparation_reasons: ["not_prepared"] })).toBe(false);
    expect(isTerminalRow({ preparation_reasons: [] })).toBe(false);
    expect(isTerminalRow({})).toBe(false);
  });
});

describe("retryLabel", () => {
  it("names what each server-reported retry actually does", () => {
    expect(retryLabel("fetch", "discovered")).toBe("⚡ Fetch JD");
    expect(retryLabel("fetch", "needs_browser")).toBe("↻ Refetch JD");
    expect(retryLabel("prefilter", "screened_out")).toBe("↻ Re-check eligibility");
    expect(retryLabel("tailor", "tailor_failed")).toBe("↻ Retry tailoring");
  });
});

describe("retryShortLabel", () => {
  it("fits the fixed-width table action as one short word or pair", () => {
    for (const [kind, status] of [["fetch", "discovered"], ["fetch", "needs_browser"], ["prefilter", "screened_out"], ["tailor", "tailor_failed"]] as const) {
      expect(retryShortLabel(kind, status).length).toBeLessThanOrEqual(8);
    }
    expect(retryShortLabel("fetch", "discovered")).toBe("Fetch JD");
  });
});

describe("canContinueFill", () => {
  const row = { status: "awaiting_review", archived_at: null, preparation_eligible: true, fill: { browser_target_id: "T1" } } as Parameters<typeof canContinueFill>[0];

  it("resumes a fill that stopped for input in its retained tab", () => {
    expect(canContinueFill(row)).toBe(true);
    expect(canContinueFill({ ...row, status: "awaiting_otp" })).toBe(true);
    expect(canContinueFill({ ...row, status: "fill_failed" })).toBe(true);
  });

  it("needs a retained tab, an open funnel, and a prepared, unarchived row", () => {
    expect(canContinueFill({ ...row, fill: {} } as typeof row)).toBe(false);
    expect(canContinueFill({ ...row, fill: undefined })).toBe(false);
    expect(canContinueFill({ ...row, status: "submitted" })).toBe(false);
    expect(canContinueFill({ ...row, status: "filling" })).toBe(false);
    expect(canContinueFill({ ...row, status: "ready" })).toBe(false);
    expect(canContinueFill({ ...row, archived_at: "2026-09-24T00:00:00Z" })).toBe(false);
    expect(canContinueFill({ ...row, preparation_eligible: false })).toBe(false);
  });
});
