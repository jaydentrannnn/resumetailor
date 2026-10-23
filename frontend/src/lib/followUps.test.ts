import { describe, expect, it } from "vitest";
import type { FollowUpRow } from "../api";
import { followUpSummary } from "./followUps";

const row = (id: string, extra: Partial<FollowUpRow> = {}): FollowUpRow => ({
  application_id: id,
  company: "Acme",
  role: "Analyst",
  sent_on: "2026-10-01",
  days_since_sent: 21,
  due: "follow_up",
  stale: false,
  ...extra,
});

describe("followUpSummary", () => {
  it("is empty when nothing is due", () => {
    expect(followUpSummary({ due: [], stale: [] })).toBe("");
  });

  it("names follow-ups, thank-yous and silent rows, counting a silent row once", () => {
    const old = row("c", { stale: true, days_since_sent: 70 });
    expect(
      followUpSummary({
        due: [row("a"), row("b", { due: "thank_you" }), old],
        stale: [old],
      }),
    ).toBe(
      "1 application is due a follow-up; 1 thank-you note to send; 1 application has had no reply in 60+ days.",
    );
    expect(followUpSummary({ due: [row("a"), row("b")], stale: [] })).toBe(
      "2 applications are due a follow-up.",
    );
  });
});
