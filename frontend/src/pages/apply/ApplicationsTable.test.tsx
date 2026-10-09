// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow } from "../../api";
import { ApplicationsTable, type TableActions } from "./ApplicationsTable";
import type { ApplicationTableState } from "./useApplicationTable";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const row = (status: string, archived = false, id = "one"): ApplicationRow => ({
  source_job_id: id,
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
  retailor: vi.fn(),
  move: vi.fn(),
  undo: vi.fn(),
  retry: vi.fn(),
  mark: vi.fn(),
  skip: vi.fn(),
  focusTab: vi.fn(),
  detail: (item) => `/applications/${item.source_job_id}`,
  rememberScroll: vi.fn(),
};

function show(
  status: string,
  archived = false,
  selectedRows: ApplicationRow[] = [],
  patch: Partial<ApplicationRow> = {},
  review = false,
) {
  const state = {
    data: {
      applications: [{ ...row(status, archived), ...patch }],
      counts: { [status]: 1 },
      total: 1,
    },
    selected: new Set(selectedRows.map((item) => item.source_job_id)),
    selectedRows,
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
  } as unknown as ApplicationTableState;
  render(
    <MemoryRouter>
      <ApplicationsTable
        scope={archived ? "archive" : review ? "review" : "queue"}
        state={state}
        actions={actions}
        empty="Empty"
        onClearSearch={vi.fn()}
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

  it.each(["ready", "awaiting_review", "fill_failed", "tailor_failed"])(
    "offers Tailor files again on a %s row whose files are fine",
    (status) => {
      show(status);
      const item = screen.getAllByRole("menuitem", { name: /Tailor files again/ })[0];
      fireEvent.click(item);
      expect(actions.retailor).toHaveBeenCalledWith([expect.objectContaining({ status })]);
    },
  );

  it.each(["submitted", "skipped", "filling", "tailoring", "submit_unconfirmed"])(
    "does not offer Tailor files again on a %s row",
    (status) => {
      show(status);
      expect(screen.queryByRole("menuitem", { name: /Tailor files again/ })).toBeNull();
    },
  );
});

describe("ApplicationsTable ready rows and long text", () => {
  it("opens the complete review question supplied by the server", () => {
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
    const question = "What are your salary expectations for this role, including bonus?";
    show("awaiting_review", false, [], { review_summary: question }, true);
    fireEvent.keyDown(document, { key: "Escape" });
    const reason = `Answer "${question}"`;
    fireEvent.click(screen.getAllByRole("button", { name: `Why it needs you: ${reason}` })[0]);
    expect(screen.getByRole("dialog", { name: "Why it needs you" }).textContent).toContain(reason);
  });

  it("makes Fill the solid green ready-to-fill button", () => {
    show("ready");
    const [fill] = screen.getAllByRole("button", { name: "Fill" });
    expect(fill.className).toContain("bg-accent");
    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
  });

  it("shows Check resume and a Review link on a ready row the server won't fill", () => {
    show("ready", false, [], {
      preparation_eligible: false,
      preparation_reasons: ["resume_quality_unverified"],
    });
    expect(screen.queryByRole("button", { name: "Fill" })).toBeNull();
    expect(screen.getAllByText("Check resume").length).toBeGreaterThan(0);
    const [review] = screen.getAllByRole("link", { name: "Review" });
    expect(review.getAttribute("href")).toBe("/applications/one");
    expect(screen.queryByRole("link", { name: "View" })).toBeNull();
  });

  it("keeps a long error on one line and opens it in a box on click", () => {
    vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(400);
    vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
    const error = "The form rejected the upload because the file was larger than allowed";
    show("tailor_failed", false, [], { error });
    fireEvent.keyDown(document, { key: "Escape" });
    const [line] = screen.getAllByRole("button", { name: `Error details: ${error}` });
    expect(line.className).toContain("truncate");
    fireEvent.click(line, { clientX: 30, clientY: 30 });
    expect(screen.getByRole("dialog", { name: "Error details" }).textContent).toContain(error);
  });
});

describe("ApplicationsTable bulk bar", () => {
  const picked = [
    row("ready", false, "one"),
    row("submitted", false, "two"),
    row("ready", false, "three"),
  ];

  it("skips only the selected rows that are not finished, and counts rows on other pages", () => {
    show("ready", false, picked);
    expect(screen.getByText("(2 on other pages)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Skip (2)" }));
    expect(actions.skip).toHaveBeenCalledWith([
      expect.objectContaining({ source_job_id: "one" }),
      expect.objectContaining({ source_job_id: "three" }),
    ]);
  });

  it("has no Skip on the Done tab", () => {
    show("ready", true, [row("ready", true, "one")]);
    expect(screen.queryByRole("button", { name: /^Skip/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
  });
});
