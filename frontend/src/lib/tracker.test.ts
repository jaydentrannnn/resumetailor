import { describe, expect, it } from "vitest";
import type { TrackerBoard, TrackerCard } from "../api";
import {
  NO_FILTERS,
  byColumn,
  closeReasons,
  filterCards,
  initials,
  moveTargets,
  optimistic,
  withCard,
} from "./tracker";

const card = (patch: Partial<TrackerCard>): TrackerCard => ({
  id: "a",
  company: "Acme",
  role: "Data Analyst",
  location: "Remote",
  source: "t",
  column: "applied",
  label: "Applied",
  reached: "",
  closed: null,
  stage: "applied",
  stage_dates: {},
  sent_on: "2026-09-10",
  last_update: "2026-09-10",
  proposals: [],
  ...patch,
});

describe("tracker", () => {
  it("filters on words, the sent range and emails", () => {
    const cards = [
      card({ id: "a" }),
      card({ id: "b", company: "Globex", sent_on: "2026-10-01" }),
      card({ id: "c", company: "Hooli", sent_on: null, column: "not_sent" }),
    ];
    expect(filterCards(cards, { ...NO_FILTERS, q: "glob analyst" }).map((c) => c.id)).toEqual(["b"]);
    expect(filterCards(cards, { ...NO_FILTERS, from: "2026-09-15" }).map((c) => c.id)).toEqual(["b"]);
    expect(filterCards(cards, { ...NO_FILTERS, until: "2026-09-15" }).map((c) => c.id)).toEqual(["a"]);
    expect(filterCards(cards, { ...NO_FILTERS, email: true })).toEqual([]);
  });

  it("groups by column and never moves a card into or out of Not sent", () => {
    const groups = byColumn([card({}), card({ id: "n", column: "not_sent" })]);
    expect(groups.applied).toHaveLength(1);
    expect(groups.not_sent).toHaveLength(1);
    expect(moveTargets(card({ column: "not_sent" }))).toEqual([]);
    expect(moveTargets(card({}))).not.toContain("not_sent");
  });

  it("offers declining only after an offer, and not the reason it already has", () => {
    expect(closeReasons(card({ stage: "interview" }))).toEqual(["rejected", "ghosted", "withdrawn"]);
    expect(closeReasons(card({ stage: "offer", closed: "rejected", column: "closed" }))).toEqual([
      "ghosted",
      "withdrawn",
      "offer_declined",
    ]);
  });

  it("shows a move at once and recounts the board", () => {
    const moved = optimistic(card({ column: "interview", label: "Interviewing" }), "closed", "ghosted");
    expect([moved.column, moved.label, moved.reached]).toEqual(["closed", "No reply", "Interviewing"]);
    const board: TrackerBoard = {
      cards: [card({})],
      unmatched: [],
      counts: { not_sent: 0, applied: 1, assessment: 0, interview: 0, offer: 0, closed: 0 },
      last_synced: "",
      auto_closed: [],
      mail: { configured: false, username: "", last_checked: "", last_error: "", running: false },
    };
    const next = withCard(board, optimistic(card({}), "offer"));
    expect(next.counts.applied).toBe(0);
    expect(next.counts.offer).toBe(1);
    expect(next.cards[0].label).toBe("Offer");
  });

  it("makes a company mark", () => {
    expect(initials("Acme Analytics, Inc.")).toBe("AA");
    expect(initials("globex")).toBe("GL");
  });
});
