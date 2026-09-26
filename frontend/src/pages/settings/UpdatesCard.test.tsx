// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UpdateStatus } from "../../api";
import { UpdateChip } from "../../components/UpdateChip";
import { UpdatesCard } from "./AboutSection";

afterEach(() => cleanup());

const fetchUpdateStatus = vi.fn();
const checkForUpdate = vi.fn();
const installUpdate = vi.fn();
vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  fetchUpdateStatus: () => fetchUpdateStatus(),
  checkForUpdate: () => checkForUpdate(),
  installUpdate: () => installUpdate(),
}));

const base: UpdateStatus = {
  supported: true,
  current: "0.1.1",
  state: "up_to_date",
  available: null,
  pct: null,
  last_checked: null,
  error: null,
  waiting_for: null,
  backup: null,
};
const offer: UpdateStatus = {
  ...base,
  state: "available",
  available: { version: "0.2.0", notes: "Faster fills", date: "" },
};

beforeEach(() => {
  fetchUpdateStatus.mockReset();
  checkForUpdate.mockReset();
  installUpdate.mockReset();
});

describe("UpdatesCard", () => {
  it("explains source and Docker copies update outside the app", async () => {
    fetchUpdateStatus.mockResolvedValue({ ...base, supported: false });
    render(<UpdatesCard />);
    await waitFor(() => expect(screen.getByText(/runs from source or Docker/)).toBeTruthy());
    expect(screen.queryByText("Check now")).toBeNull();
  });

  it("offers an update with its notes and installs on click", async () => {
    fetchUpdateStatus.mockResolvedValue(offer);
    installUpdate.mockResolvedValue({ ...offer, state: "downloading", pct: 0 });
    render(<UpdatesCard />);
    await waitFor(() => expect(screen.getByText("Version 0.2.0 is available.")).toBeTruthy());
    expect(screen.getByText("Faster fills")).toBeTruthy();
    fireEvent.click(screen.getByText("Install and restart"));
    await waitFor(() => expect(installUpdate).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByRole("progressbar")).toBeTruthy());
  });

  it("checks on request and shows a refusal", async () => {
    fetchUpdateStatus.mockResolvedValue(base);
    checkForUpdate.mockRejectedValue(new Error("Updates are unavailable"));
    render(<UpdatesCard />);
    await waitFor(() => expect(screen.getByText("Check now")).toBeTruthy());
    fireEvent.click(screen.getByText("Check now"));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/unavailable/));
  });

  it("says what an install is waiting for", async () => {
    fetchUpdateStatus.mockResolvedValue({
      ...offer,
      state: "waiting",
      waiting_for: "an Apply operation",
    });
    render(<UpdatesCard />);
    await waitFor(() =>
      expect(screen.getByText(/installs when an Apply operation finishes/)).toBeTruthy(),
    );
    expect(screen.queryByText("Install and restart")).toBeNull();
  });
});

describe("UpdateChip", () => {
  it("links to Settings → About when an update is available", async () => {
    fetchUpdateStatus.mockResolvedValue(offer);
    render(
      <MemoryRouter>
        <UpdateChip />
      </MemoryRouter>,
    );
    const chip = await screen.findByText("Update available");
    expect(chip.closest("a")?.getAttribute("href")).toBe("/settings?tab=about");
  });

  it("stays hidden when up to date", async () => {
    fetchUpdateStatus.mockResolvedValue(base);
    const { container } = render(
      <MemoryRouter>
        <UpdateChip />
      </MemoryRouter>,
    );
    await waitFor(() => expect(fetchUpdateStatus).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
  });
});
