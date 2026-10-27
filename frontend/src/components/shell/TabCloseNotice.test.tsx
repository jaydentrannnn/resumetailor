// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TabCloseNotice } from "./TabCloseNotice";

const api = vi.hoisted(() => ({
  getOpenTabs: vi.fn(),
  keepApplicationTab: vi.fn(),
}));
vi.mock("../../api", () => api);

beforeEach(() => {
  api.getOpenTabs.mockResolvedValue({
    reachable: true,
    target_ids: ["T1"],
    closing: [{ id: "a", company: "Acme", due_in: 24 }],
  });
  api.keepApplicationTab.mockResolvedValue({ kept: true, was_closing: true });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows a finished application's tab countdown with Keep open (audit #4)", async () => {
  render(<TabCloseNotice />);
  expect(await screen.findByText(/tab in 24s/)).toBeTruthy();
  expect(screen.getByText("Acme")).toBeTruthy();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Keep open" }));
  });
  expect(api.keepApplicationTab).toHaveBeenCalledWith("a");
  expect(screen.queryByText(/tab in/)).toBeNull();
});

it("shows nothing when no tab is closing", async () => {
  api.getOpenTabs.mockResolvedValue({ reachable: true, target_ids: [], closing: [] });
  render(<TabCloseNotice />);
  await act(async () => {});
  expect(screen.queryByRole("status")).toBeNull();
});
