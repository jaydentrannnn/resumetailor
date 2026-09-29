// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import type { CatalogEntry, SourceCatalog, SourceConfig } from "../../api";
import { ToastProvider } from "../../components/ui";
import { ConfirmProvider } from "../../state/confirmState";
import { AddSourceDialog } from "./AddSourceDialog";
import { PhraseChips } from "./SourceEditors";
import { SourcesTab } from "./SourcesTab";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mk = (id: string, version = "1", fields: CatalogEntry["fields"] = ["swe"]): CatalogEntry => ({
  id,
  name: `${id} name`,
  description: `${id} desc`,
  fields,
  version,
  template: {
    id,
    kind: "simplify_html",
    url: `https://x/${id}`,
    categories: ["A"],
    enabled: true,
  },
});

const CATALOG: SourceCatalog = {
  schema_version: 1,
  origin: "remote",
  entries: [
    mk("simplify-internships"),
    mk("simplify-newgrad"),
    mk("speedyapply"),
    mk("finance-list", "1", ["finance"]),
  ],
};

const SRC: SourceConfig = {
  id: "simplify-internships",
  kind: "simplify_html",
  url: "https://x/simplify-internships",
  categories: ["A"],
  enabled: true,
};

function renderTab(sources: SourceConfig[], onChange = vi.fn(), catalog = CATALOG) {
  vi.spyOn(api, "fetchSourceCatalog").mockResolvedValue(catalog);
  render(
    <MemoryRouter>
      <ToastProvider>
        <ConfirmProvider>
          <SourcesTab sources={sources} onChange={onChange} saveError={null} />
        </ConfirmProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  return onChange;
}

describe("PhraseChips", () => {
  it("adds on Enter, splits on comma and stops at five", () => {
    const onChange = vi.fn();
    const { rerender } = render(<PhraseChips query="" onChange={onChange} />);
    const input = screen.getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(input, { target: { value: "data analyst" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("data analyst");
    fireEvent.change(input, { target: { value: "risk," } });
    expect(onChange).toHaveBeenLastCalledWith("risk");
    rerender(<PhraseChips query="a, b, c, d, e" onChange={onChange} />);
    expect(
      (screen.getByLabelText("Search phrases", { selector: "input" }) as HTMLInputElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByLabelText("Remove phrase c"));
    expect(onChange).toHaveBeenLastCalledWith("a, b, d, e");
  });
});

describe("SourcesTab", () => {
  it("shows the empty state", () => {
    renderTab([]);
    expect(screen.getByText("No sources yet")).toBeTruthy();
  });

  it("removes any source after confirming", async () => {
    const onChange = renderTab([SRC]);
    fireEvent.click(screen.getByLabelText("Remove simplify-internships"));
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([]));
  });

  it("restores the missing defaults", async () => {
    const onChange = renderTab([SRC]);
    await screen.findByText("Restore defaults");
    await waitFor(() => expect(api.fetchSourceCatalog).toHaveBeenCalled());
    fireEvent.click(screen.getByText("Restore defaults"));
    fireEvent.click(await screen.findByRole("button", { name: "Restore" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const next = onChange.mock.calls[0][0] as SourceConfig[];
    expect(next.map((s) => s.id)).toEqual([
      "simplify-internships",
      "simplify-newgrad",
      "speedyapply",
    ]);
  });

  it("shows an update badge and applies it only on click", async () => {
    const newer = mk("simplify-internships", "2");
    newer.template = { ...newer.template, url: "https://x/new", categories: ["A", "B"] };
    const onChange = renderTab(
      [{ ...SRC, catalog_id: "simplify-internships", catalog_version: "1" }],
      vi.fn(),
      { ...CATALOG, entries: [newer] },
    );
    await screen.findByText("Update available");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Review update"));
    const region = screen.getByRole("region", { name: /Update for/ });
    expect(within(region).getByText(/https:\/\/x\/new/)).toBeTruthy();
    expect(within(region).getByText(/\+ B/)).toBeTruthy();
    fireEvent.click(within(region).getByRole("button", { name: "Update" }));
    expect(onChange.mock.calls[0][0][0]).toMatchObject({
      url: "https://x/new",
      catalog_version: "2",
    });
  });

  it("tests a source and lists the sample", async () => {
    vi.spyOn(api, "testSource").mockResolvedValue({
      rows_total: 12,
      rows_kept: 4,
      sample: [
        {
          company: "Acme",
          role: "Analyst",
          location: "NYC",
          age: "2d",
          posted_at: "",
          application_link: null,
        },
      ],
      errors: ["phrase x failed"],
    });
    renderTab([SRC]);
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    const panel = await screen.findByRole("region", { name: "Test result" });
    expect(panel.textContent).toContain("12 postings found");
    expect(panel.textContent).toContain("4 would be kept");
    expect(panel.textContent).toContain("Acme");
    expect(panel.textContent).toContain("phrase x failed");
  });

  it("shows a failed test", async () => {
    vi.spyOn(api, "testSource").mockRejectedValue(new Error("boom"));
    renderTab([SRC]);
    fireEvent.click(screen.getByRole("button", { name: "Test" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Test failed");
  });
});

describe("AddSourceDialog", () => {
  function open(sources: SourceConfig[] = [], onAdd = vi.fn()) {
    vi.spyOn(api, "fetchSecrets").mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "ADZUNA_APP_ID", set: true, source: "saved" },
        { name: "ADZUNA_APP_KEY", set: true, source: "saved" },
      ],
    });
    render(
      <MemoryRouter>
        <AddSourceDialog
          sources={sources}
          catalog={CATALOG}
          catalogError=""
          onAdd={onAdd}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );
    return onAdd;
  }

  it("filters the catalog by field and disables added entries", () => {
    open([SRC]);
    expect(
      (screen.getByLabelText("simplify-internships name added") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Finance" }));
    expect(screen.queryByText("speedyapply name")).toBeNull();
    expect(screen.getByText("finance-list name")).toBeTruthy();
  });

  it("adds a catalog entry", () => {
    const onAdd = open();
    fireEvent.click(screen.getByLabelText("Add finance-list name"));
    expect(onAdd.mock.calls[0][0]).toMatchObject({ catalog_id: "finance-list", enabled: true });
  });

  it("inspects a README URL, then tests and adds it", async () => {
    vi.spyOn(api, "inspectSource").mockResolvedValue({
      kind: "company_link_table",
      sections: ["Acme"],
      row_count: 9,
    });
    const onAdd = open();
    fireEvent.click(screen.getByRole("tab", { name: "README URL" }));
    fireEvent.change(screen.getByLabelText("README link"), {
      target: { value: "https://github.com/o/r" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    await screen.findByText(/Per-company role tables/);
    fireEvent.click(screen.getByLabelText("Acme"));
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    expect(onAdd.mock.calls[0][0]).toMatchObject({
      kind: "company_link_table",
      url: "https://github.com/o/r",
      categories: ["Acme"],
    });
  });

  it("reports a README with no job table", async () => {
    vi.spyOn(api, "inspectSource").mockResolvedValue({ kind: null, sections: [], row_count: 0 });
    open();
    fireEvent.click(screen.getByRole("tab", { name: "README URL" }));
    fireEvent.change(screen.getByLabelText("README link"), { target: { value: "https://x/y" } });
    fireEvent.click(screen.getByRole("button", { name: "Check" }));
    expect((await screen.findByRole("alert")).textContent).toContain("No job table found");
  });

  it("keeps Add disabled until a phrase is entered", async () => {
    const onAdd = open();
    fireEvent.click(screen.getByRole("tab", { name: "Keyword search" }));
    const add = screen.getByRole("button", { name: "Add search" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    const input = screen.getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(input, { target: { value: "analyst" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(add.disabled).toBe(false));
    fireEvent.click(add);
    expect(onAdd.mock.calls[0][0]).toMatchObject({ kind: "job_search", query: "analyst" });
  });

  it("gives each new watchlist its own id", () => {
    const existing: SourceConfig = {
      id: "company-watchlist",
      kind: "ats_board",
      url: "",
      categories: [],
      enabled: true,
      boards: [],
    };
    const onAdd = open([existing]);
    fireEvent.click(screen.getByRole("tab", { name: "Company watchlist" }));
    fireEvent.click(screen.getByRole("button", { name: "Add watchlist" }));
    expect(onAdd.mock.calls[0][0]).toMatchObject({ id: "company-watchlist-2", kind: "ats_board" });
  });
});
