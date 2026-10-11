// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { sessionMessage } from "../../../lib/layoutEditMessage";
import { LayoutEditSection } from "./LayoutEditSection";

const api = vi.hoisted(() => ({
  fetchConfig: vi.fn(),
  fetchEditSession: vi.fn(),
  startEditSession: vi.fn(),
  reopenEditSession: vi.fn(),
  importEditSession: vi.fn(),
  fetchEditedLayout: vi.fn(),
  endEditSession: vi.fn(),
}));
vi.mock("../../../api", () => api);

const template = vi.hoisted(() => ({
  info: { active_label: "Nina" },
  wizardStep: "idle",
  beginFromAnalysis: vi.fn(),
}));
vi.mock("../../../state/templateState", () => ({ useTemplateState: () => template }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../state/confirmState", () => ({ useConfirm: () => ({ confirm }) }));

const idle = {
  active: false,
  changed: false,
  saved_at: null,
  editor_open: false,
  started_at: null,
  path: null,
};

beforeEach(() => {
  api.fetchConfig.mockResolvedValue({ desktop: true });
  api.fetchEditSession.mockResolvedValue(idle);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("renders nothing outside the desktop app", async () => {
  api.fetchConfig.mockResolvedValue({ desktop: false });
  const { container } = render(<LayoutEditSection />);
  await waitFor(() => expect(api.fetchConfig).toHaveBeenCalled());
  expect(container.textContent).toBe("");
  expect(api.fetchEditSession).not.toHaveBeenCalled();
});

it("starts a session, then reviews the saved file in the wizard", async () => {
  const opened = { ...idle, active: true, editor_open: true };
  api.startEditSession.mockImplementation(async () => {
    api.fetchEditSession.mockResolvedValue(opened);
    return opened;
  });
  render(<LayoutEditSection />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit layout in Word" }));
  expect(await screen.findByText(/Open in Word/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Review changes" }).hasAttribute("disabled")).toBe(
    true,
  );

  const saved = { ...idle, active: true, changed: true, saved_at: "2026-10-11T10:00:00Z" };
  api.reopenEditSession.mockImplementation(async () => {
    api.fetchEditSession.mockResolvedValue(saved);
    return saved;
  });
  fireEvent.click(screen.getByRole("button", { name: "Open again" }));
  expect(await screen.findByText(/Saved at/)).toBeTruthy();

  const analysis = { source_sha256: "a".repeat(64), suggested_profile: {}, ready: true };
  const file = new File(["x"], "layout.docx");
  api.importEditSession.mockResolvedValue(analysis);
  api.fetchEditedLayout.mockResolvedValue(file);
  fireEvent.click(screen.getByRole("button", { name: "Review changes" }));
  await waitFor(() =>
    expect(template.beginFromAnalysis).toHaveBeenCalledWith(file, analysis, "Nina (edited)"),
  );
  expect(api.fetchEditedLayout).toHaveBeenCalledWith(analysis.source_sha256);
});

it("discards only after confirming", async () => {
  api.fetchEditSession.mockResolvedValue({ ...idle, active: true });
  render(<LayoutEditSection />);
  confirm.mockResolvedValueOnce(false);
  fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
  await waitFor(() => expect(confirm).toHaveBeenCalled());
  expect(api.endEditSession).not.toHaveBeenCalled();

  confirm.mockResolvedValueOnce(true);
  api.endEditSession.mockImplementation(async () => {
    api.fetchEditSession.mockResolvedValue(idle);
  });
  fireEvent.click(screen.getByRole("button", { name: "Discard" }));
  await waitFor(() => expect(api.endEditSession).toHaveBeenCalled());
  expect(await screen.findByRole("button", { name: "Edit layout in Word" })).toBeTruthy();
});

it("tells a Word closed without saving apart from one not opened yet", () => {
  const waiting = { ...idle, active: true };
  expect(sessionMessage(waiting)).toMatch(/^Waiting for the layout file to open/);
  expect(sessionMessage({ ...waiting, editor_closed: true })).toBe(
    "Word was closed without saving. Open it again, or discard.",
  );
  const saved = { ...waiting, changed: true, editor_closed: true, saved_at: null };
  expect(sessionMessage(saved)).not.toMatch(/keep Word open/);
});
