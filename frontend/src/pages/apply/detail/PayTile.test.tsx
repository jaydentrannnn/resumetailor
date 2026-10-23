// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { ApplicationPay, PayFigure } from "../../../api";
import { PayTile } from "./PayTile";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(cleanup);

const figure = (patch: Partial<PayFigure>): PayFigure => ({
  low: 22,
  high: 26,
  company: "Globex",
  role: "Data Analytics Intern",
  location: "Dallas, TX",
  on: "2026-09-01",
  source: "Saved posting",
  excerpt: "Hourly rate: $22 - $26",
  app_id: "b",
  sample_size: null,
  median: null,
  currency: "USD",
  period: "hour",
  ...patch,
});

const pay: ApplicationPay = {
  posted: [],
  family: "Data and machine learning",
  level: "Intern or co-op",
  groups: [
    {
      kind: "near",
      label: "Intern or co-op, data and machine learning, in TX",
      n: 1,
      sources: ["Saved posting"],
      first_on: "2026-09-01",
      last_on: "2026-09-01",
      splits: [
        {
          currency: "USD",
          period: "hour",
          n: 1,
          p25: null,
          median: null,
          p75: null,
          figures: [figure({})],
        },
      ],
    },
    {
      kind: "anywhere",
      label: "Intern or co-op, data and machine learning, anywhere",
      n: 6,
      sources: ["Campus survey", "Saved posting"],
      first_on: "2026-08-01",
      last_on: "2026-09-20",
      splits: [
        { currency: "USD", period: "hour", n: 5, p25: 22, median: 25.5, p75: 30, figures: [] },
        {
          currency: "USD",
          period: "year",
          n: 1,
          p25: null,
          median: null,
          p75: null,
          figures: [figure({ low: 60000, high: 70000, period: "year", company: "Hooli" })],
        },
      ],
    },
  ],
};

const show = (value: ApplicationPay) =>
  render(
    <MemoryRouter>
      <PayTile pay={value} />
    </MemoryRouter>,
  );

describe("PayTile", () => {
  it("lists small groups and shows percentiles from five figures up", () => {
    show(pay);
    expect(screen.getByText("$22–$26 an hour").closest("li")?.title).toBe("Hourly rate: $22 - $26");
    expect(screen.getByText("25th $22 · median $25.50 · 75th $30")).toBeTruthy();
    expect(screen.getByText("From Campus survey, Saved posting · Aug – Sep 2026")).toBeTruthy();
    // Yearly figures stay apart from hourly ones.
    expect(screen.getByText("USD, a year · 1 figure")).toBeTruthy();
    expect(screen.getByText(/not an estimate of an offer/)).toBeTruthy();
  });

  it("points to imported pay data when nothing similar states pay", () => {
    show({ ...pay, groups: [] });
    expect(screen.getByRole("link", { name: "Import pay data" }).getAttribute("href")).toBe(
      "/settings?tab=data",
    );
  });
});
