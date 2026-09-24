import { describe, expect, it } from "vitest";
import { pollSignature, shouldRefreshTables, type ApplyPollSnapshot } from "./applyPoll";

const idle = (
  operationId: string | null,
  state: string | null = "completed",
): ApplyPollSnapshot => ({ operationId, state, dailyRunning: false });

describe("Applications poll refresh", () => {
  it("refreshes while an operation or the daily run is live", () => {
    expect(shouldRefreshTables(null, idle("a", "running"), false)).toBe(true);
    expect(
      shouldRefreshTables(null, { operationId: null, state: null, dailyRunning: true }, false),
    ).toBe(true);
  });

  it("refreshes once for an operation that started and finished between two polls", () => {
    const before = pollSignature(idle("a"));
    expect(shouldRefreshTables(before, idle("b"), false)).toBe(true);
    expect(shouldRefreshTables(pollSignature(idle("b")), idle("b"), false)).toBe(false);
  });

  it("refreshes when the same operation reaches a terminal state", () => {
    expect(
      shouldRefreshTables(
        pollSignature(idle("a", "running")),
        idle("a", "completed_with_issues"),
        false,
      ),
    ).toBe(true);
  });

  it("keeps refreshing while a row is still tailoring or filling", () => {
    expect(shouldRefreshTables(pollSignature(idle("a")), idle("a"), true)).toBe(true);
  });

  it("does nothing on the first quiet poll", () => {
    expect(shouldRefreshTables(null, idle("a"), false)).toBe(false);
  });
});
