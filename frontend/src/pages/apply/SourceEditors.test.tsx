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
  it("renders inputs for query, location and country, with no key inputs", () => {
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <JobSearchEditor source={defaultSource} onChange={onChange} />
      </MemoryRouter>,
    );

    expect(screen.getByText("Search engine:").parentElement!.textContent).toContain("Adzuna");
    expect(screen.getByText("python developer")).toBeTruthy();
    expect((screen.getByLabelText("Search location") as HTMLInputElement).value).toBe("Austin, TX");
    expect((screen.getByLabelText("Adzuna country code") as HTMLInputElement).value).toBe("us");
    expect(screen.queryByLabelText("Adzuna app ID")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    const phrase = screen.getByLabelText("Search phrases", { selector: "input" });
    fireEvent.change(phrase, { target: { value: "golang engineer" } });
    fireEvent.keyDown(phrase, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({
      ...defaultSource,
      query: "python developer, golang engineer",
    });
  });

  it("fills phrases and title filters from a preset", async () => {
    vi.spyOn(api, "fetchSearchPresets").mockResolvedValue({
      positions: [
        { id: "fpa", label: "FP&A & treasury" },
        { id: "markets", label: "Sales, trading & research" },
      ],
      levels: [
        { id: "intern", label: "Internship" },
        { id: "new_grad", label: "New grad / entry level" },
      ],
      industries: [{ id: "corporate-finance", label: "Corporate finance", positions: ["fpa"] }],
    });
    const build = vi.spyOn(api, "buildSearchPreset").mockResolvedValue({
      query: "fp&a analyst intern",
      include: ["intern"],
      exclude: ["senior"],
    });
    const onChange = vi.fn();
    render(
      <MemoryRouter>
        <JobSearchEditor source={defaultSource} onChange={onChange} />
      </MemoryRouter>,
    );
    const fill = await screen.findByRole("button", { name: "Fill search" });
    expect((fill as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Preset industry"), {
      target: { value: "corporate-finance" },
    });
    expect(
      screen.getByRole("button", { name: "FP&A & treasury" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(fill);
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        ...defaultSource,
        query: "fp&a analyst intern",
        include: ["intern"],
        exclude: ["senior"],
      }),
    );
    expect(build).toHaveBeenCalledWith(["fpa"], "intern");
  });

  it("hides the country for USAJobs", () => {
    render(
      <MemoryRouter>
        <JobSearchEditor source={{ ...defaultSource, provider: "usajobs" }} onChange={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Search engine:").parentElement!.textContent).toContain("USAJobs");
    expect(screen.queryByLabelText("Adzuna country code")).toBeNull();
  });

  it("points at the Connect dialog instead of asking for keys", () => {
    const onConnect = vi.fn();
    render(
      <MemoryRouter>
        <JobSearchEditor
          source={defaultSource}
          onChange={vi.fn()}
          connected={false}
          onConnect={onConnect}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Connect Adzuna first");
    fireEvent.click(screen.getByRole("button", { name: "Connect Adzuna" }));
    expect(onConnect).toHaveBeenCalled();
    expect(screen.queryByLabelText("Adzuna app key")).toBeNull();
  });
});
