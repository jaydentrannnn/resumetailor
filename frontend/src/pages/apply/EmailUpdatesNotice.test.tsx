// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MailProposal } from "../../api";
import { mailSummary } from "../../lib/mailUpdates";
import { EmailUpdatesNotice } from "./EmailUpdatesNotice";

const api = vi.hoisted(() => ({
  getMailProposals: vi.fn(),
  acceptMailProposal: vi.fn(),
  dismissMailProposal: vi.fn(),
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../api", () => api);
vi.mock("../../lib/toast", () => ({ useToast: () => toast }));

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const proposal = (patch: Partial<MailProposal>): MailProposal => ({
  id: "p1",
  message_id: "m1",
  received_on: "2026-10-20",
  sender: "jobs@acme.com",
  from_domain: "acme.com",
  subject: "Your application to Acme",
  excerpt: "Unfortunately, we will not be moving forward.",
  signal: "rejected",
  app_id: "acme",
  candidates: [],
  reason: "Matched by company named.",
  flag: "",
  state: "pending",
  company: "Acme",
  role: "Analyst",
  stage: "Applied",
  options: [],
  ...patch,
});

const unmatched = proposal({
  id: "p2",
  subject: "Thanks for applying",
  signal: "sent",
  app_id: null,
  company: "",
  role: "",
  stage: "",
  options: [{ id: "u", company: "Initech", role: "Intern", stage: "Not sent" }],
});
const flagged = proposal({ id: "p3", flag: "This application already has an offer recorded." });
const second = proposal({ id: "p4", app_id: "globex", company: "Globex" });

async function openReview(proposals: MailProposal[]) {
  api.getMailProposals.mockResolvedValue({ proposals });
  api.acceptMailProposal.mockResolvedValue({});
  render(<EmailUpdatesNotice revision={0} onChanged={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Review" }));
}

describe("EmailUpdatesNotice", () => {
  it("shows nothing when no email is waiting", async () => {
    api.getMailProposals.mockResolvedValue({ proposals: [] });
    const { container } = render(<EmailUpdatesNotice revision={0} onChanged={vi.fn()} />);
    await waitFor(() => expect(api.getMailProposals).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("needs an application picked before an unmatched email is accepted", async () => {
    await openReview([unmatched]);
    const accept = screen.getByRole("button", { name: "Accept" });
    expect((accept as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Application"), { target: { value: "u" } });
    fireEvent.click(accept);
    await waitFor(() =>
      expect(api.acceptMailProposal).toHaveBeenCalledWith("p2", { signal: "sent", app_id: "u" }),
    );
  });

  it("accepts all matched emails but skips flagged and unmatched ones", async () => {
    await openReview([proposal({}), unmatched, flagged, second]);
    expect(screen.getByText(/Check this: This application already has an offer/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Accept all 2 matched" }));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Recorded 2 from email"));
    expect(api.acceptMailProposal.mock.calls.map(([id]) => id)).toEqual(["p1", "p4"]);
  });

  it("dismisses without recording anything", async () => {
    api.dismissMailProposal.mockResolvedValue({});
    await openReview([proposal({})]);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(api.dismissMailProposal).toHaveBeenCalledWith("p1"));
    expect(api.acceptMailProposal).not.toHaveBeenCalled();
  });

  it("summarises how many emails wait and how many are unmatched", () => {
    expect(mailSummary([proposal({}), unmatched])).toBe(
      "2 job emails to review, 1 not matched to an application. Nothing is recorded until you accept.",
    );
  });
});
