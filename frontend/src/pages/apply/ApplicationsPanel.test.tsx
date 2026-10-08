// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplyTab } from "../../lib/applyPage";
import { ApplicationsPanel } from "./ApplicationsPanel";
import type { TableActions } from "./ApplicationsTable";
import type { ApplicationTableState } from "./useApplicationTable";

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  listExtensionCaptures: vi.fn().mockResolvedValue([]),
}));

afterEach(cleanup);

const table = () =>
  ({
    data: { applications: [], counts: {}, total: 0 },
    dataQ: "",
    selected: new Set(),
    selectedRows: [],
    setSelected: vi.fn(),
    clearSelection: vi.fn(),
    q: "",
    status: "",
    page: 0,
    size: 25,
    sort: "status_at",
    direction: "desc",
    change: vi.fn(),
    refresh: vi.fn(),
    loading: false,
    error: null,
  }) as unknown as ApplicationTableState;

const actions = {
  busy: false,
  active: false,
  browserConnected: true,
  openTabs: { reachable: true, target_ids: [] },
} as unknown as TableActions;

function Panel() {
  const [tab, setTab] = useState<ApplyTab>("needs");
  return (
    <ApplicationsPanel
      tab={tab}
      onTab={setTab}
      q=""
      onQuery={vi.fn()}
      search=""
      review={table()}
      queue={table()}
      archive={table()}
      archiveTotal={0}
      actions={actions}
      progress={{ tools: null, bulk: null, note: null }}
      reviewBulk={null}
      anySource
      lastChecked={null}
      onFind={vi.fn()}
    />
  );
}

describe("ApplicationsPanel tabs", () => {
  it("keeps focus on the tablist while the arrow keys switch tabs", () => {
    render(
      <MemoryRouter>
        <Panel />
      </MemoryRouter>,
    );
    const needs = screen.getByRole("tab", { name: /Needs you/ });
    needs.focus();
    fireEvent.keyDown(needs, { key: "ArrowRight" });
    const progress = screen.getByRole("tab", { name: /In progress/ });
    expect(progress.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(progress);
    screen.getByText("No new postings");
    fireEvent.keyDown(progress, { key: "ArrowRight" });
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: /Done/ }));
  });

  it("never nests the tablist inside a tabpanel", () => {
    const { container } = render(
      <MemoryRouter>
        <Panel />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(1);
    expect(container.querySelector('[role="tabpanel"] [role="tablist"]')).toBeNull();
  });
});
