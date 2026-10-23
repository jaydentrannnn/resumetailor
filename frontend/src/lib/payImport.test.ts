import { describe, expect, it } from "vitest";
import type { PayField } from "../api";
import { missingColumns } from "./payImport";

const none = Object.fromEntries(
  [
    "company",
    "role",
    "level",
    "location",
    "currency",
    "period",
    "low",
    "high",
    "median",
    "sample_size",
    "source",
    "as_of",
  ].map((k) => [k, ""]),
) as Record<PayField, string>;

describe("missingColumns", () => {
  it("names the required fields and the pay figures still unmapped", () => {
    expect(missingColumns(none)).toBe(
      "Pick a column for role or title, currency, pay period, a low and high, or a median.",
    );
    expect(
      missingColumns({ ...none, role: "Title", currency: "Ccy", period: "Per", low: "Min" }),
    ).toBe("Pick a column for a low and high, or a median.");
  });

  it("is empty once a role, currency, period and a median or both bounds are mapped", () => {
    const base = { ...none, role: "Title", currency: "Ccy", period: "Per" };
    expect(missingColumns({ ...base, median: "Median" })).toBe("");
    expect(missingColumns({ ...base, low: "Min", high: "Max" })).toBe("");
  });
});
