import { describe, expect, it } from "vitest";
import { dateSpan, money, payRange } from "./pay";

describe("pay formatting", () => {
  it("shows cents only when a figure has them", () => {
    expect(money(22.5, "USD")).toBe("$22.50");
    expect(money(70000, "CAD")).toBe("CA$70,000");
    expect(money(2625, "GBP")).toBe("£2,625");
  });

  it("words a range or a single figure with its period", () => {
    expect(payRange(25, 30, "USD", "hour")).toBe("$25–$30 an hour");
    expect(payRange(27, 27, "USD", "hour")).toBe("$27 an hour");
    expect(payRange(120000, 150000, "EUR", "year")).toBe("€120,000–€150,000 a year");
  });

  it("spans posting dates by month", () => {
    expect(dateSpan("2026-09-01", "2026-09-20")).toBe("Sep 2026");
    expect(dateSpan("2026-08-03", "2026-09-20")).toBe("Aug – Sep 2026");
    expect(dateSpan("2025-12-03", "2026-01-20")).toBe("Dec 2025 – Jan 2026");
    expect(dateSpan("", "")).toBe("");
  });
});
