// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import type { SourceConfig } from "../../api";
import { JobSearchEditor } from "./SourceEditors";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const defaultSource: SourceConfig = {
  id: "search-1",
  kind: "job_search",
  provider: "adzuna",
  query: "python developer",
  location: "Austin, TX",
  country: "us",
  url: "",
  categories: [],
  enabled: true,
  include: ["fastapi"],
  exclude: ["lead"],
  locations: ["TX"],
  max_age_days: 14,
};

describe("JobSearchEditor", () => {
  it("renders inputs for provider, query, location, and country", async () => {
    vi.spyOn(api, "fetchSecrets").mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "ADZUNA_APP_ID", set: true, source: "saved" },
        { name: "ADZUNA_APP_KEY", set: true, source: "saved" },
      ],
    });

    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <JobSearchEditor source={defaultSource} onChange={onChange} />
      </MemoryRouter>,
    );

    expect((screen.getByLabelText("Job search provider") as HTMLSelectElement).value).toBe(
      "adzuna",
    );
    expect(screen.getByText("python developer")).toBeTruthy();
    expect((screen.getByLabelText("Search location") as HTMLInputElement).value).toBe("Austin, TX");
    expect((screen.getByLabelText("Adzuna country code") as HTMLInputElement).value).toBe("us");

    const phrase = screen.getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(phrase, { target: { value: "golang engineer" } });
    fireEvent.keyDown(phrase, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({
      ...defaultSource,
      query: "python developer, golang engineer",
    });
  });

  it("switches provider to usajobs and hides country input", async () => {
    vi.spyOn(api, "fetchSecrets").mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "USAJOBS_API_KEY", set: true, source: "saved" },
        { name: "USAJOBS_EMAIL", set: true, source: "saved" },
      ],
    });

    const onChange = vi.fn();
    const usajobsSource: SourceConfig = {
      ...defaultSource,
      provider: "usajobs",
    };

    render(
      <MemoryRouter>
        <JobSearchEditor source={usajobsSource} onChange={onChange} />
      </MemoryRouter>,
    );

    expect((screen.getByLabelText("Job search provider") as HTMLSelectElement).value).toBe(
      "usajobs",
    );
    expect(screen.queryByLabelText("Adzuna country code")).toBeNull();
  });

  it("saves missing credentials inline", async () => {
    vi.spyOn(api, "fetchSecrets").mockResolvedValue({
      backend: "keyring",
      secrets: [
        { name: "ADZUNA_APP_ID", set: false, source: "none" },
        { name: "ADZUNA_APP_KEY", set: false, source: "none" },
      ],
    });

    render(
      <MemoryRouter>
        <JobSearchEditor source={defaultSource} onChange={vi.fn()} />
      </MemoryRouter>,
    );

    const save = vi.spyOn(api, "saveSecret").mockResolvedValue({
      name: "ADZUNA_APP_ID",
      set: true,
      source: "saved",
    });
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Missing credentials: ADZUNA_APP_ID, ADZUNA_APP_KEY");
    fireEvent.change(screen.getByLabelText("Adzuna app ID"), { target: { value: "id1" } });
    fireEvent.change(screen.getByLabelText("Adzuna app key"), { target: { value: "key1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save keys" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(save).toHaveBeenCalledWith("ADZUNA_APP_ID", "id1");
    expect(save).toHaveBeenCalledWith("ADZUNA_APP_KEY", "key1");
  });
});
