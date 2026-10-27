import { describe, expect, it } from "vitest";
import type { ApplicationRow } from "../api";
import { bulkMarkable, canMark, nextAction } from "./applicationActions";

const row = (status: string, patch: Partial<ApplicationRow> = {}): ApplicationRow =>
  ({
    source_job_id: status,
    company: "Acme",
    role: "Engineer",
    status,
    archived_at: null,
    job_id: "run-1",
    preparation_eligible: true,
    ...patch,
  }) as ApplicationRow;

const tab = { browser_target_id: "t1" } as ApplicationRow["fill"];

describe("nextAction", () => {
  it.each([
    ["ready", {}, null, "fill"],
    ["awaiting_review", { fill: tab }, new Set(["t1"]), "continue"],
    ["awaiting_review", {}, null, "review"],
    ["tailor_failed", { retry_kind: "tailor" }, null, "retry"],
    ["submitted", {}, null, "view"],
    ["ready", { archived_at: "2026-10-01T00:00:00Z" }, null, "view"],
  ] as const)("%s %j → %s", (status, patch, openTabs, expected) => {
    expect(nextAction(row(status, patch as Partial<ApplicationRow>), openTabs)).toBe(expected);
  });

  it("reviews a ready row the server won't fill", () => {
    const blocked = row("ready", {
      preparation_eligible: false,
      preparation_reasons: ["resume_missing"],
    });
    expect(nextAction(blocked, null)).toBe("review");
  });
});

describe("marking", () => {
  it("offers Mark submitted on every unfinished row, a filling one included", () => {
    expect(canMark(row("filling"))).toBe(true);
    expect(canMark(row("tailoring"))).toBe(true);
    expect(canMark(row("skipped"))).toBe(false);
    expect(canMark(row("ready", { archived_at: "2026-10-01T00:00:00Z" }))).toBe(false);
  });

  it("leaves held and finished rows out of a bulk mark", () => {
    const rows = [row("ready"), row("filling"), row("submitted")];
    expect(bulkMarkable(rows, new Set(["filling"])).map((item) => item.status)).toEqual([
      "ready",
    ]);
  });
});
