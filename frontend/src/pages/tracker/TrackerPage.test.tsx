// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MailProposal, TrackerBoard, TrackerCard } from "../../api";
import { TrackerPage } from "./TrackerPage";

const api = vi.hoisted(() => ({
  getTrackerBoard: vi.fn(),
  moveTrackerCard: vi.fn(),
  undoTrackerMove: vi.fn(),
  acceptMailProposal: vi.fn(),
  dismissMailProposal: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../api", () => api);
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));
vi.mock("../../state/workspaceState", () => ({
  useWorkspaceState: () => ({ activeId: "default" }),
}));

const card = (patch: Partial<TrackerCard>): TrackerCard => ({
  id: "acme",
  company: "Acme",
  role: "Data Analyst",
  location: "Remote",
  source: "t",
  column: "applied",
  label: "Applied",
  reached: "",
  closed: null,
  stage: "applied",
  stage_dates: {},
  sent_on: "2026-09-10",
  last_update: "2026-09-10",
  proposals: [],
  ...patch,
});

const email = (patch: Partial<MailProposal>): MailProposal => ({
  id: "p1",
  message_id: "m1",
  received_on: "2026-10-20",
  sender: "jobs@globex.com",
  from_domain: "globex.com",
  subject: "Interview invitation",
  excerpt: "We'd like to invite you.",
  signal: "interview_invited",
  app_id: null,
  candidates: [],
  reason: "",
  flag: "",
  state: "pending",
  company: "",
  role: "",
  stage: "",
  options: [],
  ...patch,
});

function board(cards: TrackerCard[], unmatched: MailProposal[] = []): TrackerBoard {
  const counts = { not_sent: 0, applied: 0, assessment: 0, interview: 0, offer: 0, closed: 0 };
  for (const c of cards) counts[c.column] += 1;
  return { cards, unmatched, counts, last_synced: "2026-10-21T10:00:00+00:00" };
}

const dataTransfer = { setData: vi.fn(), effectAllowed: "", dropEffect: "" };
const column = (id: string) => document.querySelector(`[data-tracker-column="${id}"]`)!;
const cardEl = (id: string) => document.querySelector(`[data-tracker-card="${id}"]`)!;

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/tracker"]}>
      <TrackerPage />
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TrackerPage", () => {
  it("shows the columns with Not sent hidden until asked for", async () => {
    api.getTrackerBoard.mockResolvedValue(
      board([card({}), card({ id: "skip", company: "Hooli", column: "not_sent", label: "Skipped", stage: null })]),
    );
    renderPage();
    await screen.findByText("Data Analyst", { selector: "button" });
    expect(column("applied")).toBeTruthy();
    expect(column("not_sent")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show Not sent" }));
    expect(within(column("not_sent") as HTMLElement).getByText("Restore on the Apply page")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide Interviewing" }));
    expect(column("interview")).toBeNull();
  });

  it("records a drag, offers Undo, and rolls back a refused move", async () => {
    api.getTrackerBoard.mockResolvedValue(board([card({})]));
    const moved = card({ column: "interview", label: "Interviewing", stage: "interview" });
    // The server's board follows each change, as the real one does.
    api.moveTrackerCard.mockImplementationOnce(async () => {
      api.getTrackerBoard.mockResolvedValue(board([moved]));
      return { card: moved, receipt: { added: ["e1"], voided: [] } };
    });
    api.undoTrackerMove.mockImplementationOnce(async () => {
      api.getTrackerBoard.mockResolvedValue(board([card({})]));
      return card({});
    });
    renderPage();
    await screen.findByText("Data Analyst", { selector: "button" });

    fireEvent.dragStart(cardEl("acme"), { dataTransfer });
    fireEvent.dragOver(column("interview"), { dataTransfer });
    fireEvent.drop(column("interview"), { dataTransfer });
    await waitFor(() => expect(api.moveTrackerCard).toHaveBeenCalledWith("acme", "interview", undefined));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(within(column("interview") as HTMLElement).getByText("Data Analyst")).toBeTruthy();
    const [, , action] = toast.success.mock.calls[0];
    action.onClick();
    await waitFor(() => expect(api.undoTrackerMove).toHaveBeenCalledWith("acme", { added: ["e1"], voided: [] }));

    api.moveTrackerCard.mockRejectedValueOnce(new Error("This stage comes from an older status mark"));
    await waitFor(() => expect(within(column("applied") as HTMLElement).getByText("Data Analyst")).toBeTruthy());
    fireEvent.dragStart(cardEl("acme"), { dataTransfer });
    fireEvent.dragOver(column("offer"), { dataTransfer });
    fireEvent.drop(column("offer"), { dataTransfer });
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(within(column("applied") as HTMLElement).getByText("Data Analyst")).toBeTruthy();
  });

  it("asks why a card closed, and Escape keeps it where it was", async () => {
    api.getTrackerBoard.mockResolvedValue(board([card({ stage: "interview", column: "interview" })]));
    api.moveTrackerCard.mockResolvedValue({
      card: card({ column: "closed", closed: "ghosted", label: "No reply", reached: "Interviewing" }),
      receipt: { added: ["e2"], voided: [] },
    });
    renderPage();
    await screen.findByText("Data Analyst", { selector: "button" });
    fireEvent.dragStart(cardEl("acme"), { dataTransfer });
    fireEvent.dragOver(column("closed"), { dataTransfer });
    fireEvent.drop(column("closed"), { dataTransfer });
    const ask = screen.getByRole("group", { name: "Why did Acme close?" });
    expect(within(ask).queryByRole("button", { name: "Offer declined" })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Why did Acme close?" })).toBeNull();
    expect(api.moveTrackerCard).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Actions for Acme" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Closed…" }));
    fireEvent.click(screen.getByRole("button", { name: "No reply" }));
    await waitFor(() => expect(api.moveTrackerCard).toHaveBeenCalledWith("acme", "closed", "ghosted"));
  });

  it("accepts and dismisses an email on its card", async () => {
    const flagged = email({ id: "p9", app_id: "acme", flag: "Already rejected." });
    api.getTrackerBoard.mockResolvedValue(
      board([card({ proposals: [email({ app_id: "acme", company: "Acme" }), flagged] })]),
    );
    api.acceptMailProposal.mockResolvedValue({});
    api.dismissMailProposal.mockResolvedValue({});
    renderPage();
    const accepts = await screen.findAllByRole("button", { name: "Accept" });
    fireEvent.click(accepts[0]);
    await waitFor(() => expect(api.acceptMailProposal).toHaveBeenCalledWith("p1", {}));
    fireEvent.click(screen.getAllByRole("button", { name: "Accept" })[1]);
    expect(api.acceptMailProposal).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Record anyway" }));
    await waitFor(() => expect(api.acceptMailProposal).toHaveBeenCalledWith("p9", {}));
    fireEvent.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);
    await waitFor(() => expect(api.dismissMailProposal).toHaveBeenCalledWith("p1"));
  });

  it("asks before recording a tray email dropped on a card", async () => {
    api.getTrackerBoard.mockResolvedValue(board([card({})], [email({})]));
    api.acceptMailProposal.mockResolvedValue({});
    renderPage();
    await screen.findByText("Emails to assign");
    fireEvent.dragStart(document.querySelector('[data-tracker-email="p1"]')!, { dataTransfer });
    fireEvent.dragOver(cardEl("acme"), { dataTransfer });
    fireEvent.drop(cardEl("acme"), { dataTransfer });
    expect(api.acceptMailProposal).not.toHaveBeenCalled();
    const confirm = screen.getByRole("group", { name: "Confirm email" });
    expect(confirm.textContent).toContain("Invited to interview");
    fireEvent.click(within(confirm).getByRole("button", { name: "Record" }));
    await waitFor(() => expect(api.acceptMailProposal).toHaveBeenCalledWith("p1", { app_id: "acme" }));
  });

  it("moves a card from the list view's Stage select", async () => {
    api.getTrackerBoard.mockResolvedValue(board([card({})]));
    api.moveTrackerCard.mockResolvedValue({ card: card({}), receipt: { added: [], voided: [] } });
    render(
      <MemoryRouter initialEntries={["/tracker?view=list"]}>
        <TrackerPage />
      </MemoryRouter>,
    );
    const select = await screen.findByRole("combobox", { name: "Stage of Acme" });
    fireEvent.change(select, { target: { value: "closed:withdrawn" } });
    await waitFor(() => expect(api.moveTrackerCard).toHaveBeenCalledWith("acme", "closed", "withdrawn"));
  });
});
