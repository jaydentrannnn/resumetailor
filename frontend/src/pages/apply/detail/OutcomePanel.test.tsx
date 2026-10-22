// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow, OutcomeEvent } from "../../../api";
import { OutcomePanel } from "./OutcomePanel";

const api = vi.hoisted(() => ({ recordOutcome: vi.fn(), correctOutcome: vi.fn() }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock("../../../api", () => api);
vi.mock("../../../lib/toast", () => ({ useToast: () => toast }));

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const event = (patch: Partial<OutcomeEvent>): OutcomeEvent => ({
  id: "e1",
  type: "interview_invited",
  occurred_on: "2026-10-20",
  recorded_at: "2026-10-20T10:00:00+00:00",
  source: "manual",
  note: "",
  replaces: null,
  voided_at: null,
  ...patch,
});

const app = (patch: Partial<ApplicationRow> = {}) =>
  ({
    source_job_id: "a",
    company: "Acme",
    role: "Analyst",
    status: "submitted",
    hiring: {
      stage: "interview",
      closed: null,
      responded: true,
      stage_dates: { applied: "2026-10-01", interview: "2026-10-20" },
      label: "Interviewing",
    },
    outcome_events: [],
    attempts: [],
    ...patch,
  }) as unknown as ApplicationRow;

describe("OutcomePanel", () => {
  it("records what happened and hands back the saved row", async () => {
    const saved = app();
    api.recordOutcome.mockResolvedValue(saved);
    const onSaved = vi.fn();
    render(<OutcomePanel app={app()} onSaved={onSaved} />);
    expect(screen.getByText("Interviewing")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("What happened"), { target: { value: "offer" } });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "Verbal" } });
    fireEvent.click(screen.getByRole("button", { name: "Record" }));
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    await vi.waitFor(() =>
      expect((screen.getByLabelText("Note (optional)") as HTMLTextAreaElement).value).toBe(""),
    );
    expect(api.recordOutcome).toHaveBeenCalledWith("a", {
      type: "offer",
      occurred_on: null,
      note: "Verbal",
    });
  });

  it("edits through a correction and removes by voiding, keeping history visible", async () => {
    api.correctOutcome.mockResolvedValue(app());
    const live = event({ id: "e2", type: "rejected", replaces: "e1", note: "Form email" });
    const old = event({ id: "e1", voided_at: "2026-10-21T00:00:00+00:00" });
    render(<OutcomePanel app={app({ outcome_events: [old, live] })} onSaved={vi.fn()} />);
    expect(screen.getByText("Corrected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByText("Correct this event")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    await vi.waitFor(() =>
      expect(api.correctOutcome).toHaveBeenCalledWith("a", "e2", {
        type: "rejected",
        occurred_on: "2026-10-20",
        note: "Form email",
      }),
    );
    await screen.findByText("Record what happened");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await vi.waitFor(() =>
      expect(api.correctOutcome).toHaveBeenLastCalledWith("a", "e2", { void: true }),
    );
  });

  it("says when a marked submission's upload is unconfirmed", () => {
    const attempt = {
      id: "t1",
      number: 1,
      submitted_at: "2026-10-01T10:00:00+00:00",
      method: "manual" as const,
      confirmed: false,
      snapshot_dir: "C:/out/a/attempts/1",
      files: { "tailored.pdf": "x" },
      voided_at: null,
      error: "",
    };
    render(<OutcomePanel app={app({ attempts: [attempt] })} onSaved={vi.fn()} />);
    expect(screen.getByText(/what you uploaded isn't confirmed/)).toBeTruthy();
    expect(screen.getByText("tailored.pdf")).toBeTruthy();
  });
});
