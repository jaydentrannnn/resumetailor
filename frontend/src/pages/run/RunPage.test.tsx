// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../../state/runState", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../state/runState")>();
  const { DEFAULT_SETTINGS } = await import("../../state/runDefaults");
  return {
    ...actual,
    useRunState: () => ({
      config: null,
      jdText: "",
      setJdText: () => {},
      settings: DEFAULT_SETTINGS,
      setSettings: () => {},
      jobId: "job-1",
      status: "succeeded",
      events: [],
      report: null,
      expansion: null,
      skills: null,
      coverLetter: null,
      setCoverLetter: () => {},
      error: null,
      busy: false,
      queuePosition: null,
      settingsLoaded: true,
      settingsSaveState: "saved",
      settingsSaveError: null,
      flushSettings: async () => {},
      startJob: async () => {},
      cancelRun: async () => {},
      cancelling: false,
      history: [],
      historyLoaded: true,
    }),
  };
});
vi.mock("../../state/workspaceState", () => ({
  useWorkspaceState: () => ({ switching: false, activeId: "default" }),
}));
vi.mock("../../components/DocumentsCard", () => ({ DocumentsCard: () => <p>documents panel</p> }));
vi.mock("../../components/RunHistoryPanel", () => ({ RunHistoryPanel: () => null }));

import { RunPage } from "./RunPage";

afterEach(cleanup);

describe("RunPage", () => {
  it("shows the run's documents beside the selected pane, which stays selected", () => {
    render(
      <MemoryRouter>
        <RunPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("documents panel")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Job" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "Review bullets" }));
    expect(screen.getByRole("tab", { name: "Review bullets" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    fireEvent.click(screen.getByRole("tab", { name: "Application content" }));
    expect(
      screen.getByRole("tab", { name: "Application content" }).getAttribute("aria-selected"),
    ).toBe("true");
    expect(screen.getByText("documents panel")).toBeTruthy();
  });

  it("puts Tailor again under the posting and History in the command bar", () => {
    render(
      <MemoryRouter>
        <RunPage />
      </MemoryRouter>,
    );
    const pane = screen.getByRole("region", { name: "Job and results" });
    expect(within(pane).getByRole("button", { name: "Tailor again" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.queryByRole("region", { name: "Job and results" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Tailor" }));
    expect(screen.getByRole("region", { name: "Job and results" })).toBeTruthy();
  });
});
