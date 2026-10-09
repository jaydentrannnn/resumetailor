// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { AttentionItem, DailyStatus } from "../../api";
import { NightlyRunTile } from "./NightlyRunTile";

afterEach(cleanup);

const daily = (fields: Partial<DailyStatus> = {}): DailyStatus => ({
  running: true,
  phase: "discovering",
  source_id: "",
  current: "",
  processed: 2,
  total: 10,
  dry_run: false,
  fetch_only: false,
  started_at: "2026-10-08T01:00:00",
  finished_at: "",
  date: "2026-10-08",
  summary: { attention: [] },
  ...fields,
});

const renderTile = (status: DailyStatus) =>
  render(
    <MemoryRouter>
      <NightlyRunTile daily={status} />
    </MemoryRouter>,
  );

describe("NightlyRunTile", () => {
  it("shows the nightly run's progress while it runs", () => {
    renderTile(daily());
    expect(screen.getByText("Nightly run in progress")).toBeTruthy();
  });

  it("stays hidden while a Find jobs runs through the same pass", () => {
    const { container } = renderTile(daily({ fetch_only: true }));
    expect(container.textContent).toBe("");
  });

  it("stays hidden after a Find jobs that left items to review", () => {
    const attention: AttentionItem[] = [
      { application_id: "a", label: "Acme — Engineer", kind: "failed", message: "x", at: "" },
    ];
    const { container } = renderTile(
      daily({
        running: false,
        fetch_only: true,
        finished_at: "2026-10-08T01:05:00",
        summary: { attention },
      }),
    );
    expect(container.textContent).toBe("");
  });
});
