// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplyOperation, InFlightItem } from "../../api";
import { OperationBanner } from "./OperationBanner";

afterEach(() => cleanup());

const item = (application_id: string, step: number): InFlightItem => ({
  application_id,
  label: `Acme · ${application_id}`,
  job_id: "",
  step,
  step_id: "",
  action_label: "Completing form",
  field_label: "",
  stage: "filling",
  started_at: "2026-01-01T00:00:00Z",
  deadline_at: "2026-01-01T00:04:00Z",
});

const operation = (in_flight: InFlightItem[]): ApplyOperation => ({
  operation_id: "op",
  action: "fill",
  state: "running",
  application_ids: ["one", "two"],
  in_flight,
  current_application_id: "two",
  current_label: "Acme · two",
  stage: "filling",
  message: "",
  processed: 0,
  total: 2,
  completed: 0,
  blocked: 0,
  failed: 0,
  submitted: 0,
  started_at: "2026-01-01T00:00:00Z",
  updated_at: "",
  heartbeat_at: "",
  current_step: 2,
  application_started_at: "2026-01-01T00:00:00Z",
  finished_at: "",
  effective_model: "ollama:test",
  auto_submit: false,
  blocker_mode: "continue",
  events: [],
});

describe("OperationBanner", () => {
  it("shows newest activity first without mutating the operation events", () => {
    const op = operation([]);
    op.events = [
      { at: "2026-01-01T00:00:00Z", message: "Starting" },
      { at: "2026-01-01T00:00:01Z", message: "Starting" },
      { at: "2026-01-01T00:00:02Z", message: "Finished fetching" },
      { at: "2026-01-01T00:00:02Z", message: "Processing" },
    ];
    const original = structuredClone(op.events);
    const { container } = render(
      <MemoryRouter>
        <OperationBanner operation={op} onControl={vi.fn()} />
      </MemoryRouter>,
    );
    const activity = Array.from(container.querySelectorAll("details ul li"));
    expect(activity).toHaveLength(3);
    expect(activity[0].textContent).toContain("Processing");
    expect(activity[1].textContent).toContain("Finished fetching");
    expect(activity[2].textContent).toContain("Starting");
    expect(op.events).toEqual(original);
  });

  it("renders Find jobs percentage and counts without application progress or ETA", () => {
    render(
      <MemoryRouter>
        <OperationBanner
          operation={{
            ...operation([]),
            action: "find",
            find_progress: { phase: "processing", processed: 8, total: 20, current: "Acme" },
          }}
          onControl={vi.fn()}
        />
      </MemoryRouter>,
    );
    const bar = screen.getByRole("progressbar", { name: "Find jobs progress" });
    expect(bar.getAttribute("aria-valuenow")).toBe("70");
    expect(bar.getAttribute("aria-valuetext")).toBe("Processing postings: 8 of 20 · Acme");
    expect(screen.queryByText(/left/)).toBeNull();
    expect(screen.queryByText(/ready for you/)).toBeNull();
  });

  it("uses an indeterminate indicator for older active Find jobs operations", () => {
    render(
      <MemoryRouter>
        <OperationBanner operation={{ ...operation([]), action: "find" }} onControl={vi.fn()} />
      </MemoryRouter>,
    );
    const bar = screen.getByRole("progressbar", { name: "Progress total unknown" });
    expect(bar.hasAttribute("aria-valuenow")).toBe(false);
  });

  it("shows both active fills with their own progress", () => {
    render(
      <MemoryRouter>
        <OperationBanner
          operation={operation([item("one", 1), item("two", 2)])}
          onControl={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Filling 2 at once" })).toBeTruthy();
    expect(screen.getByText(/Acme · one · filling · Filling, page 1/)).toBeTruthy();
    expect(screen.getByText(/Acme · two · filling · Filling, page 2/)).toBeTruthy();
  });

  it("keeps the single-item headline", () => {
    render(
      <MemoryRouter>
        <OperationBanner operation={operation([item("one", 1)])} onControl={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Filling 1 of 2 · Acme · two" })).toBeTruthy();
  });

  it("names parallel prepares in the header", () => {
    render(
      <MemoryRouter>
        <OperationBanner
          operation={{ ...operation([item("one", 0), item("two", 0)]), action: "prepare" }}
          onControl={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Preparing 2 at once" })).toBeTruthy();
  });
});
