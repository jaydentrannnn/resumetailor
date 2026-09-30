// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import type {
  CatalogEntry,
  SourceCatalog,
  SourceConfig,
  SourceField,
  SourcesStatus,
} from "../../api";
import { ToastProvider } from "../../components/ui";
import { PhraseChips } from "./SourceEditors";
import type { SaveState } from "./SourcePanel";
import { SourcesTab } from "./SourcesTab";

const NOW = Date.now();
const ago = (ms: number) => new Date(NOW - ms).toISOString();

beforeEach(() => {
  vi.spyOn(api, "fetchSecrets").mockResolvedValue({ backend: "keyring", secrets: [] });
  vi.spyOn(api, "testSource").mockResolvedValue({
    rows_total: 0,
    rows_kept: 0,
    sample: [],
    errors: [],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  try {
    localStorage.clear();
  } catch {
    /* jsdom without storage */
  }
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
    url: `https://github.com/x/${id}`,
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
  name: "Internships",
  url: "https://github.com/x/simplify-internships",
  categories: ["A"],
  enabled: true,
};

/** A 0.2.8 profile: sources without `name` or `catalog_id`, an old keyword search, a custom README. */
const LEGACY: SourceConfig[] = [
  {
    id: "simplify-internships",
    kind: "simplify_html",
    url: "https://github.com/SimplifyJobs/Summer2026-Internships",
    categories: ["Software Engineering Internship Roles"],
    enabled: true,
  },
  {
    id: "speedyapply",
    kind: "pipe_table",
    url: "https://github.com/speedyapply/2026-SWE-College-Jobs",
    categories: [],
    enabled: true,
  },
  {
    id: "keyword-search",
    kind: "job_search",
    url: "",
    categories: [],
    enabled: true,
    provider: "adzuna",
    query: "financial analyst, risk",
    location: "Chicago",
    country: "us",
  },
  {
    id: "my-list",
    kind: "company_link_table",
    url: "https://github.com/o/my-list",
    categories: ["Acme"],
    enabled: false,
  },
  {
    id: "company-watchlist",
    kind: "ats_board",
    url: "",
    categories: [],
    enabled: true,
    boards: [
      { ats: "greenhouse", slug: "acme", company: "Acme Capital" },
      { ats: "lever", slug: "globex", company: "Globex" },
    ],
  },
];

type Extra = {
  status?: SourcesStatus | null;
  fields?: SourceField[];
  onFieldsChange?: (fields: SourceField[]) => void;
  saveState?: SaveState;
  saveError?: string | null;
  onFlush?: () => void;
  catalog?: SourceCatalog;
};

function Harness({
  initial,
  spy,
  extra,
}: {
  initial: SourceConfig[];
  spy: (next: SourceConfig[]) => void;
  extra: Extra;
}) {
  const [sources, setSources] = useState(initial);
  return (
    <SourcesTab
      sources={sources}
      onChange={(next) => {
        spy(next);
        setSources(next);
      }}
      saveError={extra.saveError ?? null}
      saveState={extra.saveState}
      onFlush={extra.onFlush}
      status={extra.status}
      fields={extra.fields}
      onFieldsChange={extra.onFieldsChange}
    />
  );
}

function renderTab(sources: SourceConfig[], extra: Extra = {}) {
  vi.spyOn(api, "fetchSourceCatalog").mockResolvedValue(extra.catalog ?? CATALOG);
  const onChange = vi.fn();
  const view = render(
    <MemoryRouter>
      <ToastProvider>
        <Harness initial={sources} spy={onChange} extra={extra} />
      </ToastProvider>
    </MemoryRouter>,
  );
  return { onChange, ...view };
}

/** The ids on the latest onChange call. */
const ids = (onChange: ReturnType<typeof vi.fn>) =>
  (onChange.mock.lastCall![0] as SourceConfig[]).map((s) => s.id);

function menuItem(rowName: string, item: string) {
  fireEvent.click(screen.getByRole("button", { name: `Actions for ${rowName}` }));
  return screen.findByRole("menuitem", { name: item });
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

describe("groups", () => {
  it("shows all three groups, each with its explanation and add button, when empty", () => {
    renderTab([]);
    for (const title of ["Job lists", "Search engines", "Company watchlists"])
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();
    expect(screen.getByText(/GitHub lists of internships/)).toBeTruthy();
    expect(screen.getByText(/Keyword searches through Adzuna or USAJobs/)).toBeTruthy();
    expect(screen.getByText(/Companies whose careers pages/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add job list" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add search" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add watchlist" })).toBeTruthy();
    expect(screen.getByText("No job lists yet.")).toBeTruthy();
    expect(screen.getByText("No searches yet.")).toBeTruthy();
    expect(screen.getByText("No watchlists yet.")).toBeTruthy();
  });

  it("shows Adzuna and USAJobs and how to connect them before any search exists", async () => {
    renderTab([]);
    const adzuna = screen.getByRole("group", { name: "Adzuna" });
    const usajobs = screen.getByRole("group", { name: "USAJobs" });
    expect(await within(adzuna).findByRole("button", { name: "Connect Adzuna" })).toBeTruthy();
    expect(within(usajobs).getByRole("button", { name: "Connect USAJobs" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "+ Add search" })).toBeTruthy();
  });

  it("lists each source in its own group", () => {
    renderTab(LEGACY);
    const lists = screen.getByRole("region", { name: "Job lists" });
    expect(within(lists).getAllByRole("listitem")).toHaveLength(3);
    const searches = screen.getByRole("region", { name: "Search engines" });
    expect(within(searches).getAllByRole("listitem")).toHaveLength(1);
    expect(within(searches).getByText("Adzuna: financial analyst, risk")).toBeTruthy();
    expect(within(searches).getByText("Adzuna search")).toBeTruthy();
    expect(
      within(screen.getByRole("region", { name: "Company watchlists" })).getByText(
        "Watchlist: Acme Capital, Globex",
      ),
    ).toBeTruthy();
  });
});

describe("connecting a search engine", () => {
  it("shows Connected / Not connected per provider", async () => {
    vi.mocked(api.fetchSecrets).mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "ADZUNA_APP_ID", set: true, source: "saved" },
        { name: "ADZUNA_APP_KEY", set: true, source: "saved" },
        { name: "USAJOBS_API_KEY", set: true, source: "saved" },
        { name: "USAJOBS_EMAIL", set: false, source: "none" },
      ],
    });
    renderTab([]);
    const adzuna = screen.getByRole("group", { name: "Adzuna" });
    const usajobs = screen.getByRole("group", { name: "USAJobs" });
    await within(adzuna).findByText("● Connected");
    expect(within(adzuna).getByRole("button", { name: "Change Adzuna keys" })).toBeTruthy();
    expect(within(usajobs).getByText("○ Not connected")).toBeTruthy();
    expect(within(usajobs).getByRole("button", { name: "Connect USAJobs" })).toBeTruthy();
  });

  it("saves the keys once and flips to Connected", async () => {
    vi.mocked(api.fetchSecrets)
      .mockResolvedValueOnce({ backend: "keyring", secrets: [] })
      .mockResolvedValue({
        backend: "keyring",
        secrets: [
          { name: "ADZUNA_APP_ID", set: true, source: "saved" },
          { name: "ADZUNA_APP_KEY", set: true, source: "saved" },
        ],
      });
    const save = vi
      .spyOn(api, "saveSecret")
      .mockResolvedValue({ name: "x", set: true, source: "saved" });
    renderTab([]);
    const adzuna = screen.getByRole("group", { name: "Adzuna" });
    fireEvent.click(await within(adzuna).findByRole("button", { name: "Connect Adzuna" }));
    const dialog = await screen.findByRole("dialog", { name: "Connect Adzuna" });
    const submit = within(dialog).getByRole("button", { name: "Save keys" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Adzuna app ID"), { target: { value: "id1" } });
    fireEvent.change(within(dialog).getByLabelText("Adzuna app key"), { target: { value: "k1" } });
    fireEvent.click(submit);
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenCalledWith("ADZUNA_APP_ID", "id1");
    expect(save).toHaveBeenCalledWith("ADZUNA_APP_KEY", "k1");
    await within(adzuna).findByText("● Connected");
    expect(screen.queryByRole("dialog", { name: "Connect Adzuna" })).toBeNull();
  });

  it("adds a search without asking for keys, pointing at Connect instead", async () => {
    const { onChange } = renderTab([]);
    const adzuna = screen.getByRole("group", { name: "Adzuna" });
    await within(adzuna).findByText("○ Not connected");
    fireEvent.click(screen.getByRole("button", { name: "+ Add search" }));
    const dialog = await screen.findByRole("dialog", { name: "New Adzuna search" });
    expect(within(dialog).queryByLabelText("Adzuna app key")).toBeNull();
    expect(within(dialog).getByRole("alert").textContent).toContain("Connect Adzuna first");
    const add = within(dialog).getByRole("button", { name: "Add search" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    const input = within(dialog).getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(input, { target: { value: "analyst" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(add.disabled).toBe(false));
    fireEvent.click(add);
    expect(onChange.mock.lastCall![0][0]).toMatchObject({
      kind: "job_search",
      provider: "adzuna",
      query: "analyst",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Adzuna: analyst")).toBeTruthy();
  });

  it("starts a USAJobs search on USAJobs", async () => {
    const { onChange } = renderTab([]);
    fireEvent.click(screen.getByRole("button", { name: "+ Add search" }));
    let dialog = await screen.findByRole("dialog", { name: "New Adzuna search" });
    fireEvent.change(within(dialog).getByLabelText("Search engine"), {
      target: { value: "usajobs" },
    });
    dialog = await screen.findByRole("dialog", { name: "New USAJobs search" });
    const input = within(dialog).getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(input, { target: { value: "policy" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(await within(dialog).findByRole("button", { name: "Add search" }));
    expect(onChange.mock.lastCall![0][0]).toMatchObject({ provider: "usajobs", query: "policy" });
  });
});

describe("rows", () => {
  it("gives every source of a 0.2.8 profile the same controls, with a friendly name", async () => {
    renderTab(LEGACY);
    const names = [
      "SimplifyJobs/Summer2026-Internships",
      "speedyapply/2026-SWE-College-Jobs",
      "Adzuna: financial analyst, risk",
      "o/my-list",
      "Watchlist: Acme Capital, Globex",
    ];
    for (const name of names) {
      expect(screen.getByRole("switch", { name: `${name} on` })).toBeTruthy();
      expect(screen.getByRole("checkbox", { name: `Select ${name}` })).toBeTruthy();
      const edit = await menuItem(name, "Edit");
      expect(edit).toBeTruthy();
      expect(screen.getByRole("menuitem", { name: "Remove" })).toBeTruthy();
      for (const item of ["Rename", "Duplicate"])
        expect(screen.getByRole("menuitem", { name: item })).toBeTruthy();
      expect(screen.queryByRole("menuitem", { name: "Test now" })).toBeNull();
      fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    }
    // No raw ids leak into the rows.
    expect(screen.queryByText("keyword-search")).toBeNull();
    expect(screen.queryByText("company-watchlist")).toBeNull();
  });

  it("summarises what each source searches on one line", () => {
    renderTab(LEGACY);
    expect(screen.getByText("Software Engineering Internship Roles")).toBeTruthy();
    expect(screen.getByText("Every category")).toBeTruthy();
    expect(screen.getByText("financial analyst, risk · Chicago")).toBeTruthy();
    expect(screen.getByText("Acme Capital, Globex")).toBeTruthy();
  });

  it("turns a source on and off", () => {
    const { onChange } = renderTab([SRC]);
    fireEvent.click(screen.getByRole("switch", { name: "Internships on" }));
    expect(onChange.mock.lastCall![0][0].enabled).toBe(false);
  });

  it("renames from the menu", async () => {
    const { onChange } = renderTab([SRC]);
    fireEvent.click(await menuItem("Internships", "Rename"));
    const input = screen.getByLabelText("Name for Internships");
    fireEvent.change(input, { target: { value: "Summer" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange.mock.lastCall![0][0].name).toBe("Summer");
  });

  it("duplicates right after the original", async () => {
    const { onChange } = renderTab([SRC, { ...SRC, id: "other", name: "Other" }]);
    fireEvent.click(await menuItem("Internships", "Duplicate"));
    expect(ids(onChange)).toEqual(["simplify-internships", "simplify-internships-2", "other"]);
    expect(screen.getByText("Internships copy")).toBeTruthy();
  });

  it("shows an update badge and applies it only on click", async () => {
    const newer = mk("simplify-internships", "2");
    newer.template = { ...newer.template, url: "https://x/new", categories: ["A", "B"] };
    const { onChange } = renderTab(
      [{ ...SRC, catalog_id: "simplify-internships", catalog_version: "1" }],
      { catalog: { ...CATALOG, entries: [newer] } },
    );
    await screen.findByText("Update available");
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Review update"));
    const region = screen.getByRole("region", { name: /Update for/ });
    expect(within(region).getByText(/https:\/\/x\/new/)).toBeTruthy();
    expect(within(region).getByText(/\+ B/)).toBeTruthy();
    fireEvent.click(within(region).getByRole("button", { name: "Update" }));
    expect(onChange.mock.lastCall![0][0]).toMatchObject({
      url: "https://x/new",
      catalog_version: "2",
    });
  });
});

describe("health", () => {
  const status: SourcesStatus = {
    last_run_at: ago(2 * 3600_000),
    sources: {
      "simplify-internships": {
        found: 1412,
        kept: 20,
        error: null,
        at: ago(2 * 3600_000),
      },
      "keyword-search": {
        found: 0,
        kept: 0,
        error: "needs ADZUNA_APP_KEY",
        at: ago(2 * 3600_000),
      },
    },
  };

  it("shows counts, a failure reason, never-run and off", () => {
    renderTab(LEGACY, { status });
    expect(screen.getByText(/1,412 found · 20 kept · 2h ago/)).toBeTruthy();
    const failed = screen.getByText(/needs ADZUNA_APP_KEY · 2h ago/);
    expect(failed.className).toContain("text-danger");
    // speedyapply and the watchlist have never run; the custom list is off.
    expect(screen.getAllByText("Not run yet")).toHaveLength(2);
    expect(screen.getByText("Off")).toBeTruthy();
  });

  it("names the search engine to connect when its keys are missing", async () => {
    renderTab(LEGACY);
    expect(await screen.findByText("Connect Adzuna to run this search.")).toBeTruthy();
  });

  it("writes the header line", () => {
    renderTab(LEGACY, { status });
    expect(screen.getByText("Searching 4 sources · last run 2h ago")).toBeTruthy();
  });
});

describe("removing", () => {
  it("removes without a confirm dialog and offers Undo that restores the order", async () => {
    const { onChange } = renderTab(LEGACY);
    const before = LEGACY.map((s) => s.id);
    fireEvent.click(await menuItem("o/my-list", "Remove"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(ids(onChange)).toEqual(before.filter((id) => id !== "my-list"));
    expect(screen.getByText("Removed o/my-list")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ids(onChange)).toEqual(before);
    expect(screen.getByRole("switch", { name: "o/my-list on" })).toBeTruthy();
  });

  it("bulk turns off, turns on and removes, with one Undo", async () => {
    const { onChange } = renderTab(LEGACY);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Select speedyapply/2026-SWE-College-Jobs" }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select o/my-list" }));
    const bar = screen.getByRole("toolbar", { name: "Selected sources" });
    expect(bar.textContent).toContain("2 selected");
    fireEvent.click(within(bar).getByRole("button", { name: "Turn on" }));
    let last = onChange.mock.lastCall![0] as SourceConfig[];
    expect(
      last.filter((s) => ["speedyapply", "my-list"].includes(s.id)).every((s) => s.enabled),
    ).toBe(true);
    fireEvent.click(within(bar).getByRole("button", { name: "Turn off" }));
    last = onChange.mock.lastCall![0];
    expect(
      last.filter((s) => ["speedyapply", "my-list"].includes(s.id)).every((s) => !s.enabled),
    ).toBe(true);
    expect(last.find((s) => s.id === "keyword-search")!.enabled).toBe(true);

    fireEvent.click(within(bar).getByRole("button", { name: "Remove" }));
    expect(ids(onChange)).toEqual(["simplify-internships", "keyword-search", "company-watchlist"]);
    expect(screen.queryByRole("toolbar", { name: "Selected sources" })).toBeNull();
    expect(screen.getByText("Removed 2 sources")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ids(onChange)).toEqual(LEGACY.map((s) => s.id));
  });

  it("selects every source at once", () => {
    renderTab(LEGACY);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all sources" }));
    expect(screen.getByRole("toolbar", { name: "Selected sources" }).textContent).toContain(
      "5 selected",
    );
  });
});

describe("the edit panel", () => {
  it("opens beside the list, tests the source once and autosaves edits", async () => {
    const { onChange } = renderTab([SRC], { saveState: "saved" });
    fireEvent.click(await menuItem("Internships", "Edit"));
    const panel = await screen.findByRole("dialog", { name: "Internships" });
    await waitFor(() => expect(api.testSource).toHaveBeenCalledTimes(1));
    expect(await within(panel).findByRole("region", { name: "Test result" })).toBeTruthy();
    // The row is still in the list, not expanded inline.
    expect(screen.queryByText("Done")).toBeNull();
    fireEvent.change(within(panel).getByLabelText("Name"), { target: { value: "Renamed" } });
    expect(onChange.mock.lastCall![0][0].name).toBe("Renamed");
    expect(within(panel).getByText("Saved")).toBeTruthy();
    expect(api.testSource).toHaveBeenCalledTimes(1);
  });

  it("shows the save in progress and a server validation error inline", async () => {
    renderTab([SRC], { saveState: "saving", saveError: "sources[0]: url is required" });
    fireEvent.click(await menuItem("Internships", "Edit"));
    const panel = await screen.findByRole("dialog", { name: "Internships" });
    expect(within(panel).getByText("Saving…")).toBeTruthy();
    expect(within(panel).getByRole("alert").textContent).toContain("sources[0]: url is required");
    // The page-level error is not repeated behind the panel.
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("flushes the pending save when it closes", async () => {
    const onFlush = vi.fn();
    renderTab([SRC], { onFlush });
    fireEvent.click(await menuItem("Internships", "Edit"));
    await screen.findByRole("dialog", { name: "Internships" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape", async () => {
    renderTab([SRC]);
    fireEvent.click(await menuItem("Internships", "Edit"));
    await screen.findByRole("dialog", { name: "Internships" });
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("edits a watchlist and a keyword search with the right editor", async () => {
    renderTab(LEGACY);
    fireEvent.click(await menuItem("Watchlist: Acme Capital, Globex", "Edit"));
    let panel = await screen.findByRole("dialog");
    expect(within(panel).getByLabelText("Company careers page or job board link")).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
    fireEvent.click(await menuItem("Adzuna: financial analyst, risk", "Edit"));
    panel = await screen.findByRole("dialog");
    expect(within(panel).getByLabelText("Search location")).toBeTruthy();
    expect(within(panel).queryByLabelText("Adzuna app key")).toBeNull();
  });

  it("removes from inside the panel with Undo", async () => {
    const { onChange } = renderTab([SRC]);
    fireEvent.click(await menuItem("Internships", "Edit"));
    await screen.findByRole("dialog", { name: "Internships" });
    fireEvent.click(screen.getByRole("button", { name: "Remove this source" }));
    expect(ids(onChange)).toEqual([]);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ids(onChange)).toEqual(["simplify-internships"]);
  });

  it("does not test a keyword search with no phrase", async () => {
    renderTab([{ ...LEGACY[2], query: "" }]);
    fireEvent.click(await menuItem("Adzuna search", "Edit"));
    await screen.findByRole("dialog");
    expect(api.testSource).not.toHaveBeenCalled();
  });
});

describe("paste a link", () => {
  async function paste(link: string) {
    fireEvent.click(screen.getByRole("button", { name: "+ Add job list" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a job list" });
    fireEvent.change(within(dialog).getByLabelText("Paste a link to any job list"), {
      target: { value: link },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
  }

  it("opens the same panel, prefilled, for a README", async () => {
    vi.spyOn(api, "inspectSource").mockResolvedValue({
      kind: "company_link_table",
      sections: ["Acme"],
      row_count: 9,
    });
    const resolve = vi.spyOn(api, "resolveBoard");
    const { onChange } = renderTab([]);
    await paste("https://github.com/o/r");
    const dialog = await screen.findByRole("dialog", { name: "New job list" });
    // The same filters block every other source has.
    expect(within(dialog).getByLabelText("Keep titles containing")).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByLabelText("Acme"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Add job list" }));
    expect(onChange.mock.lastCall![0][0]).toMatchObject({
      kind: "company_link_table",
      url: "https://github.com/o/r",
      categories: ["Acme"],
    });
    expect(resolve).not.toHaveBeenCalled();
  });

  it("falls back to a careers page and starts a watchlist when there is none", async () => {
    vi.spyOn(api, "inspectSource").mockResolvedValue({ kind: null, sections: [], row_count: 0 });
    vi.spyOn(api, "resolveBoard").mockResolvedValue({
      ats: "greenhouse",
      slug: "acme",
      company: "Acme Capital",
      jobs: 4,
      url: "https://boards.greenhouse.io/acme",
    });
    const { onChange } = renderTab([]);
    await paste("https://acme.com/careers");
    const dialog = await screen.findByRole("dialog", { name: "New company watchlist" });
    expect(within(dialog).getByText(/Acme Capital/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Add watchlist" }));
    expect(onChange.mock.lastCall![0][0]).toMatchObject({
      kind: "ats_board",
      boards: [{ ats: "greenhouse", slug: "acme", company: "Acme Capital" }],
    });
  });

  it("adds the company to an existing watchlist when the link is not a README", async () => {
    vi.spyOn(api, "inspectSource").mockRejectedValue(new Error("not a readme"));
    vi.spyOn(api, "resolveBoard").mockResolvedValue({
      ats: "ashby",
      slug: "initech",
      company: "Initech",
      jobs: 2,
      url: "u",
    });
    const { onChange } = renderTab(LEGACY);
    await paste("https://initech.com/jobs");
    const dialog = await screen.findByRole("dialog", { name: "Add this company" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add company" }));
    const watch = (onChange.mock.lastCall![0] as SourceConfig[]).find(
      (s) => s.id === "company-watchlist",
    )!;
    expect(watch.boards?.map((b) => b.slug)).toEqual(["acme", "globex", "initech"]);
  });

  it("says so when the link is neither", async () => {
    vi.spyOn(api, "inspectSource").mockResolvedValue({ kind: null, sections: [], row_count: 0 });
    vi.spyOn(api, "resolveBoard").mockRejectedValue(new Error("No job board found"));
    renderTab([]);
    await paste("https://example.com/nothing");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("not a job list or a careers page");
    // The catalog stays open so another link can be tried.
    expect(screen.getByRole("dialog", { name: "Add a job list" })).toBeTruthy();
  });

  it("refuses a link that is already a source", async () => {
    const inspect = vi.spyOn(api, "inspectSource");
    renderTab(LEGACY);
    await paste("https://github.com/o/my-list/");
    expect((await screen.findByRole("alert")).textContent).toContain("Already in your sources");
    expect(inspect).not.toHaveBeenCalled();
  });
});

describe("recommended for your fields", () => {
  it("lists catalog entries for the fields that are not added yet, one click each", async () => {
    const { onChange } = renderTab([SRC], { fields: ["finance"], onFieldsChange: vi.fn() });
    const strip = await screen.findByRole("region", { name: "Recommended for your fields" });
    expect(within(strip).queryByRole("button", { name: "Add simplify-newgrad name" })).toBeNull();
    fireEvent.click(within(strip).getByRole("button", { name: "Add finance-list name" }));
    expect(onChange.mock.lastCall![0].at(-1)).toMatchObject({
      catalog_id: "finance-list",
      enabled: true,
    });
    // Everything recommended is added, so the strip goes away.
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Recommended for your fields" })).toBeNull(),
    );
  });

  it("can be dismissed", async () => {
    renderTab([SRC], { fields: ["finance"], onFieldsChange: vi.fn() });
    await screen.findByRole("region", { name: "Recommended for your fields" });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss recommendations" }));
    expect(screen.queryByRole("region", { name: "Recommended for your fields" })).toBeNull();
  });

  it("changes the fields", async () => {
    const onFieldsChange = vi.fn();
    renderTab([SRC], { fields: ["finance"], onFieldsChange });
    const strip = await screen.findByRole("region", { name: "Recommended for your fields" });
    fireEvent.click(within(strip).getByRole("button", { name: "Change fields" }));
    fireEvent.click(within(strip).getByRole("button", { name: "Quant" }));
    expect(onFieldsChange).toHaveBeenLastCalledWith(["finance", "quant"]);
    fireEvent.click(within(strip).getByRole("button", { name: "Finance" }));
    expect(onFieldsChange).toHaveBeenLastCalledWith([]);
  });

  it("asks for fields when none are set", () => {
    renderTab([SRC], { fields: [], onFieldsChange: vi.fn() });
    const strip = screen.getByRole("region", { name: "Recommended for your fields" });
    expect(strip.textContent).toContain("Pick the kinds of jobs you want");
    expect(within(strip).getByRole("button", { name: "Software engineering" })).toBeTruthy();
  });
});

describe("page actions", () => {
  it("restores the missing defaults from the page menu, with Undo", async () => {
    const { onChange } = renderTab([SRC]);
    await waitFor(() => expect(api.fetchSourceCatalog).toHaveBeenCalled());
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "More source actions" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Restore defaults" }));
    expect(ids(onChange)).toEqual(["simplify-internships", "simplify-newgrad", "speedyapply"]);
    expect(screen.getByText("Restored 2 default sources")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(ids(onChange)).toEqual(["simplify-internships"]);
  });
});

describe("the catalog", () => {
  it("opens prefiltered to your fields and adds an entry", async () => {
    const { onChange } = renderTab([SRC], { fields: ["finance"] });
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "+ Add job list" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a job list" });
    expect(
      within(dialog).getByRole("button", { name: "Finance" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(within(dialog).queryByText("speedyapply name")).toBeNull();
    fireEvent.click(within(dialog).getByLabelText("Add finance-list name"));
    expect(onChange.mock.lastCall![0].at(-1)).toMatchObject({ catalog_id: "finance-list" });
    expect(within(dialog).getByLabelText("finance-list name added")).toBeTruthy();
    // Clearing the filter shows the rest, and an added entry is disabled.
    fireEvent.click(within(dialog).getByRole("button", { name: "Finance" }));
    expect(
      (within(dialog).getByLabelText("simplify-internships name added") as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(within(dialog).getByText("speedyapply name")).toBeTruthy();
  });
});

describe("watchlists", () => {
  it("needs a company, then names the new watchlist and gives it its own id", async () => {
    vi.spyOn(api, "resolveBoard").mockResolvedValue({
      ats: "greenhouse",
      slug: "acme",
      company: "Acme Capital",
      jobs: 4,
      url: "u",
    });
    const existing: SourceConfig = {
      id: "company-watchlist",
      kind: "ats_board",
      url: "",
      categories: [],
      enabled: true,
      boards: [],
    };
    const { onChange } = renderTab([existing]);
    fireEvent.click(screen.getByRole("button", { name: "+ Add watchlist" }));
    const dialog = await screen.findByRole("dialog", { name: "New company watchlist" });
    const add = within(dialog).getByRole("button", { name: "Add watchlist" }) as HTMLButtonElement;
    expect(add.disabled).toBe(true);
    fireEvent.change(within(dialog).getByLabelText("Company careers page or job board link"), {
      target: { value: "https://acme.com/careers" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add company" }));
    await waitFor(() => expect(add.disabled).toBe(false));
    fireEvent.click(add);
    expect(onChange.mock.lastCall![0][1]).toMatchObject({
      id: "company-watchlist-2",
      kind: "ats_board",
      boards: [{ slug: "acme" }],
    });
  });
});

describe("one panel for new and saved sources", () => {
  it("adding a source saves nothing until Add, and Cancel drops it", async () => {
    const { onChange } = renderTab([]);
    fireEvent.click(screen.getByRole("button", { name: "+ Add search" }));
    let dialog = await screen.findByRole("dialog", { name: "New Adzuna search" });
    const input = within(dialog).getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(input, { target: { value: "analyst" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "+ Add search" }));
    dialog = await screen.findByRole("dialog", { name: "New Adzuna search" });
    expect(within(dialog).queryByText("analyst")).toBeNull();
  });

  it("has the same fields whether the source is new or saved", async () => {
    renderTab(LEGACY);
    const fieldsOf = (dialog: HTMLElement) =>
      [
        "Search phrases",
        "Keep titles containing",
        "Skip titles containing",
        "Only these locations",
      ].map((label) => within(dialog).queryByLabelText(label, { selector: "input" }) !== null);
    fireEvent.click(screen.getByRole("button", { name: "+ Add search" }));
    const fresh = await screen.findByRole("dialog", { name: "New Adzuna search" });
    const newFields = fieldsOf(fresh);
    fireEvent.click(within(fresh).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(await menuItem("Adzuna: financial analyst, risk", "Edit"));
    const saved = await screen.findByRole("dialog", { name: "Adzuna: financial analyst, risk" });
    expect(fieldsOf(saved)).toEqual(newFields);
    expect(newFields.every(Boolean)).toBe(true);
  });

  it("gives job lists and watchlists the same filters as searches", async () => {
    renderTab(LEGACY);
    for (const name of ["o/my-list", "Watchlist: Acme Capital, Globex"]) {
      fireEvent.click(await menuItem(name, "Edit"));
      const panel = await screen.findByRole("dialog", { name });
      for (const label of [
        "Keep titles containing",
        "Skip titles containing",
        "Only these locations",
      ])
        expect(within(panel).getByLabelText(label, { selector: "input" })).toBeTruthy();
      expect(within(panel).getByLabelText("Days old limit")).toBeTruthy();
      fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
  });

  it("filters are chips: a comma or paste makes several", async () => {
    const { onChange } = renderTab([SRC]);
    fireEvent.click(await menuItem("Internships", "Edit"));
    const panel = await screen.findByRole("dialog", { name: "Internships" });
    const input = within(panel).getByLabelText("Keep titles containing", { selector: "input" });
    fireEvent.change(input, { target: { value: "analyst, associate," } });
    expect(onChange.mock.lastCall![0][0].include).toEqual(["analyst", "associate"]);
    fireEvent.click(within(panel).getByLabelText("Remove keyword analyst"));
    expect(onChange.mock.lastCall![0][0].include).toEqual(["associate"]);
  });

  it("does not show a stale key error once the keys are saved", async () => {
    vi.mocked(api.fetchSecrets).mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "ADZUNA_APP_ID", set: true, source: "saved" },
        { name: "ADZUNA_APP_KEY", set: true, source: "saved" },
      ],
    });
    renderTab(LEGACY, {
      status: {
        last_run_at: ago(3600_000),
        sources: {
          "keyword-search": {
            found: 0,
            kept: 0,
            error: "needs ADZUNA_APP_KEY",
            at: ago(3600_000),
          },
        },
      },
    });
    await screen.findByText("● Connected");
    expect(await screen.findByText(/Keys saved since the last run/)).toBeTruthy();
    expect(screen.queryByText(/needs ADZUNA_APP_KEY/)).toBeNull();
  });
});
