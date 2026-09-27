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
