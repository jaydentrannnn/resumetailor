// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
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
