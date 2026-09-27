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
    expect((screen.getByLabelText("Search keywords") as HTMLInputElement).value).toBe(
      "python developer",
    );
    expect((screen.getByLabelText("Search location") as HTMLInputElement).value).toBe("Austin, TX");
    expect((screen.getByLabelText("Adzuna country code") as HTMLInputElement).value).toBe("us");

    fireEvent.change(screen.getByLabelText("Search keywords"), {
      target: { value: "golang engineer" },
    });
    expect(onChange).toHaveBeenCalledWith({
      ...defaultSource,
      query: "golang engineer",
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

  it("displays missing credentials warning with link when keys are not set", async () => {
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

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert.textContent).toContain("Missing credentials: ADZUNA_APP_ID, ADZUNA_APP_KEY");
      expect(screen.getByText("Settings → Models").getAttribute("href")).toBe(
        "/settings?tab=models",
      );
    });
  });
});
