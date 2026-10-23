// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CompanyResearch, CompanyResearchView } from "../../../api";
import { CompanyTile } from "./CompanyTile";

const api = vi.hoisted(() => ({
  getCompanyResearch: vi.fn(),
  researchCompany: vi.fn(),
  removeCompanyFact: vi.fn(),
}));
vi.mock("../../../api", () => api);

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

const research: CompanyResearch = {
  company: "Acme",
  researched_at: "2026-10-20T10:00:00+00:00",
  sources: [
    {
      id: "s1",
      kind: "site",
      url: "https://www.acme.example/about",
      title: "About Acme",
      fetched_at: "2026-10-20T10:00:00+00:00",
      sha: "a",
      text: "Acme builds dashboards for hospitals.",
      flags: [],
    },
  ],
  facts: [
    {
      id: "f1",
      text: "Acme builds dashboards for hospitals.",
      kind: "product",
      source_id: "s1",
      excerpt: "Acme builds dashboards for hospitals.",
      as_of: "2026-10-20",
    },
  ],
  removed: [],
  dropped: 2,
  searched_with: "brave",
  warnings: ["Could not read news.example: news.example answered 403."],
  model: "fake",
};

const view = (patch: Partial<CompanyResearchView>): CompanyResearchView => ({
  company: "Acme",
  research: null,
  stale: false,
  search: "",
  ...patch,
});

const renderTile = () =>
  render(
    <MemoryRouter>
      <CompanyTile sourceJobId="acme1" />
    </MemoryRouter>,
  );

describe("CompanyTile", () => {
  it("offers research, and says only the posting is read without a search key", async () => {
    api.getCompanyResearch.mockResolvedValue(view({}));
    api.researchCompany.mockResolvedValue(view({ research }));
    renderTile();
    fireEvent.click(await screen.findByRole("button", { name: "Research company" }));
    expect(screen.getByText(/Only the posting and pages you add are read/)).toBeTruthy();
    expect(api.researchCompany).toHaveBeenCalledWith("acme1", {});
    expect(await screen.findByText("acme.example")).toBeTruthy();
  });

  it("shows each fact with its quote, source and date, and what was left out", async () => {
    api.getCompanyResearch.mockResolvedValue(view({ research, search: "brave", stale: true }));
    renderTile();
    expect(await screen.findByText("“Acme builds dashboards for hospitals.”")).toBeTruthy();
    expect(screen.getByRole("link", { name: "acme.example" }).getAttribute("href")).toBe(
      "https://www.acme.example/about",
    );
    expect(screen.getByText(/1 source · read/).textContent).toContain("over 30 days old");
    expect(screen.getByText(/2 facts were left out/)).toBeTruthy();
    expect(screen.getByText(/answered 403/)).toBeTruthy();
    expect(screen.queryByText(/Only the posting/)).toBeNull();
  });

  it("adds a link as a page and removes a fact", async () => {
    api.getCompanyResearch.mockResolvedValue(view({ research, search: "brave" }));
    api.researchCompany.mockResolvedValue(view({ research, search: "brave" }));
    api.removeCompanyFact.mockResolvedValue(view({ research: { ...research, facts: [] } }));
    renderTile();
    fireEvent.click(await screen.findByRole("button", { name: "Add a page or note" }));
    fireEvent.change(screen.getByLabelText("A link or a note about the company"), {
      target: { value: "acme.example/team" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.researchCompany).toHaveBeenCalledWith("acme1", {
        urls: ["acme.example/team"],
        notes: [],
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Remove: Acme builds/ }));
    await waitFor(() => expect(api.removeCompanyFact).toHaveBeenCalledWith("acme1", "f1"));
    expect(await screen.findByText(/No fact could be quoted/)).toBeTruthy();
  });
});
