// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VertexConnectionPanel } from "./VertexConnectionPanel";
import { useVertexConnection, vertexChanged } from "./useVertexConnection";

const api = vi.hoisted(() => ({
  connection: vi.fn(),
  models: vi.fn(),
  projects: vi.fn(),
  start: vi.fn(),
  auth: vi.fn(),
  cancel: vi.fn(),
  disconnect: vi.fn(),
  clear: vi.fn(),
}));
vi.mock("../../api", () => ({
  fetchVertexConnection: api.connection,
  fetchVertexModels: api.models,
  fetchVertexProjects: api.projects,
  startVertexAuth: api.start,
  fetchVertexAuth: api.auth,
  cancelVertexAuth: api.cancel,
  disconnectVertex: api.disconnect,
}));
vi.mock("./useModelCheck", () => ({ clearModelChecks: api.clear }));

const disconnected = { configured: true, connected: false, email: null, revision: "" };
const connected = {
  configured: true,
  connected: true,
  email: "user@example.test",
  revision: "new",
};
async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  api.connection.mockResolvedValue(disconnected);
  api.models.mockResolvedValue({
    models: [{ id: "claude-haiku-5-5", reasoning: true, locations: [] }],
  });
  api.projects.mockResolvedValue({ projects: [], next_page_token: "" });
  api.start.mockResolvedValue({
    flow_id: "opaque",
    authorization_url: "https://accounts.google.com/auth",
  });
  api.auth.mockResolvedValue({ status: "pending", detail: "Waiting" });
  api.cancel.mockResolvedValue({ status: "cancelled", detail: "Cancelled" });
  api.disconnect.mockResolvedValue(disconnected);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Google connection", () => {
  it("reports an unconfigured build and disables sign-in", async () => {
    api.connection.mockResolvedValue({ ...disconnected, configured: false });
    render(<VertexConnectionPanel />);
    await flush();
    expect(
      screen.getByRole("button", { name: "Connect Google Cloud" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(screen.getByText(/connection unavailable/i)).toBeTruthy();
  });

  it("opens the external sign-in link and refreshes checks on completion", async () => {
    render(<VertexConnectionPanel />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Connect Google Cloud" }));
    await flush();
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("link", { name: "Continue sign-in in browser" }).getAttribute("href"),
    ).toBe("https://accounts.google.com/auth");
    api.auth.mockResolvedValue({ status: "connected", detail: "Google Cloud connected." });
    api.connection.mockResolvedValue(connected);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByText(/Connected as user@example.test/)).toBeTruthy();
    expect(api.clear).toHaveBeenCalled();
  });

  it("cancels pending sign-in and removes a saved connection", async () => {
    render(<VertexConnectionPanel />);
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Connect Google Cloud" }));
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Cancel sign-in" }));
    await flush();
    expect(api.cancel).toHaveBeenCalledWith("opaque");
    api.connection.mockResolvedValue(connected);
    act(() => vertexChanged());
    await flush();
    api.connection.mockResolvedValue(disconnected);
    fireEvent.click(screen.getByRole("button", { name: "Disconnect / remove credentials" }));
    await flush();
    expect(api.disconnect).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Connect Google Cloud" })).toBeTruthy();
  });

  it("keeps manual project entry available when discovery fails", async () => {
    api.connection.mockResolvedValue(connected);
    api.projects.mockRejectedValue(new Error("denied"));
    const hook = renderHook(() => useVertexConnection(true));
    await flush();
    expect(hook.result.current.connection?.connected).toBe(true);
    expect(hook.result.current.models[0].id).toBe("claude-haiku-5-5");
    expect(hook.result.current.detail).toContain("manually");
  });

  it("discards responses from a removed connection", async () => {
    let finish!: (value: typeof connected) => void;
    api.connection.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const hook = renderHook(() => useVertexConnection(true));
    act(() => vertexChanged());
    await flush();
    await act(async () => {
      finish(connected);
    });
    expect(hook.result.current.connection?.connected).toBe(false);
  });
});
