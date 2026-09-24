// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../state/runState", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../state/runState")>();
  return {
    ...actual,
    useRunState: () => ({
      config: null,
      jdText: "",
      setJdText: () => {},
      settings: actual.DEFAULT_SETTINGS,
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
    }),
  };
});
vi.mock("../state/workspaceState", () => ({ useWorkspaceState: () => ({ switching: false }) }));
vi.mock("../components/DocumentsCard", () => ({ DocumentsCard: () => <p>documents panel</p> }));
vi.mock("../components/RunHistoryPanel", () => ({ RunHistoryPanel: () => null }));

import { RunPage } from "./RunPage";

afterEach(cleanup);

describe("RunPage tailored results tabs", () => {
  it("keeps a selected result tab instead of snapping back to Overview", () => {
    render(
      <MemoryRouter>
        <RunPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Documents" }));
    expect(screen.getByRole("tab", { name: "Documents" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(screen.getByText("documents panel")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Application content" }));
    expect(
      screen.getByRole("tab", { name: "Application content" }).getAttribute("aria-selected"),
    ).toBe("true");
  });
});
