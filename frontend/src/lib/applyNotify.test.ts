import { describe, expect, it } from "vitest";
import { type ApplySnapshot, applyNotifications } from "./applyNotify";

const base: ApplySnapshot = {
  needsYou: 1,
  otp: [],
  dailyRunning: false,
  dailySummary: null,
  operationId: null,
  operationState: null,
  operationAction: null,
  readyForReview: 0,
};

describe("applyNotifications", () => {
  it("stays quiet on first load and when nothing changed", () => {
    expect(applyNotifications(null, { ...base, needsYou: 5 })).toEqual([]);
    expect(applyNotifications(base, base)).toEqual([]);
  });

  it("announces an emailed code once, without double-counting it as needs-you", () => {
    const next = { ...base, needsYou: 2, otp: ["k1:Acme"] };
    expect(applyNotifications(base, next)).toEqual(["Enter the code sent to your email for Acme"]);
    expect(applyNotifications(next, next)).toEqual([]);
  });

  it("reports more rows needing you, a finished nightly run and a finished fill", () => {
    expect(applyNotifications(base, { ...base, needsYou: 5 })).toEqual(["5 applications need you"]);
    expect(
      applyNotifications(
        { ...base, dailyRunning: true },
        { ...base, dailySummary: { new_rows: 12, tailored: 8, submitted: 5 } },
      ),
    ).toEqual(["Nightly run finished: 12 found, 8 tailored, 5 submitted"]);
    expect(
      applyNotifications(
        { ...base, operationId: "o", operationState: "running", operationAction: "fill" },
        {
          ...base,
          operationId: "o",
          operationState: "completed",
          operationAction: "fill",
          readyForReview: 3,
        },
      ),
    ).toEqual(["Filling finished: 3 ready for you"]);
  });
});
