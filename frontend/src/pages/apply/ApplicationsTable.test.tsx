// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow } from "../../api";
import { ApplicationsTable, type TableActions } from "./ApplicationsTable";
import type { ApplicationTableState } from "./useApplicationTable";

afterEach(cleanup);

const row = (status: string, archived = false): ApplicationRow => ({
  source_job_id: "one",
  company: "Acme",
  role: "Engineer",
  location: "Remote",
  posting_url: "",
  final_url: "",
  ats: "unknown",
  status,
  discovered_at: "2026-09-30T00:00:00Z",
  archived_at: archived ? "2026-09-30T01:00:00Z" : null,
  job_id: "run-1",
  preparation_eligible: true,
  screen: null,
  error: null,
  notes: "",
  sources: [],
  group_size: 1,
  salary: "",
  eligibility_flags: [],
  duplicate_of: null,
});

const actions: TableActions = {
  busy: false,
  active: false,
  browserConnected: true,
  openTabs: { reachable: true, target_ids: [] },
  start: vi.fn(),
  reopen: vi.fn(),
  move: vi.fn(),
  undo: vi.fn(),
  retry: vi.fn(),
  mark: vi.fn(),
  focusTab: vi.fn(),
  detail: (item) => `/applications/${item.source_job_id}`,
  rememberScroll: vi.fn(),
};

function show(status: string, archived = false) {
  const state = {
    data: { applications: [row(status, archived)], counts: { [status]: 1 }, total: 1 },
    selected: new Set<string>(),
    setSelected: vi.fn(),
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
  } as unknown as ApplicationTableState;
  render(
    <MemoryRouter>
      <ApplicationsTable
        scope={archived ? "archive" : "queue"}
        state={state}
        actions={actions}
        empty="Empty"
      />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getAllByRole("button", { name: "More actions for Acme Engineer" })[0]);
}

describe("ApplicationsTable actions", () => {
  it.each(["submitted", "skipped"])("offers undo for active %s", (status) => {
    show(status);
    expect(
      screen.getAllByRole("menuitem", { name: "Not submitted — move back" }).length,
    ).toBeGreaterThan(0);
  });

  it("labels an archived submitted row's restore action", () => {
    show("submitted", true);
    expect(
      screen.getAllByRole("menuitem", { name: "Restore (undo submitted)" }).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("menuitem", { name: "Not submitted — move back" })).toBeNull();
  });

  it("offers Fill as the primary action after a ready row is restored", () => {
    show("ready");
    expect(screen.getAllByRole("button", { name: "Fill" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("menuitem", { name: "Not submitted — move back" })).toBeNull();
  });
});
