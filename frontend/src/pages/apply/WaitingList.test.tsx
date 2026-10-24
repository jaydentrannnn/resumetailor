// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow, WaitingItem } from "../../api";
import { ProgressBulkActions } from "./ProgressToolbar";
import { WaitingList } from "./WaitingList";

vi.mock("../../state/commandState", () => ({ useCommands: () => {} }));

afterEach(() => cleanup());

const waiting: WaitingItem = {
  application_id: "one",
  label: "Acme · Analyst",
  due_at: "2026-01-01T00:03:00Z",
  comebacks: 1,
  reason: "Answer 2 questions",
  answered: false,
};

describe("WaitingList", () => {
  it("counts down and offers Open tab, Retry now and Leave it", () => {
    const onControl = vi.fn();
    const onOpenTab = vi.fn();
    render(
      <MemoryRouter>
        <WaitingList
          items={[waiting]}
          now={Date.parse("2026-01-01T00:01:00Z")}
          onControl={onControl}
          onOpenTab={onOpenTab}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("waiting-item").textContent).toContain(
      "Answer 2 questions · Comes back in 2:00",
    );
    fireEvent.click(screen.getByRole("button", { name: "Open tab" }));
    expect(onOpenTab).toHaveBeenCalledWith("one");
    fireEvent.click(screen.getByRole("button", { name: "Retry now" }));
    expect(onControl).toHaveBeenCalledWith("retry_now", "one");
    fireEvent.click(screen.getByRole("button", { name: "Leave it" }));
    expect(onControl).toHaveBeenCalledWith("leave", "one");
  });

  it("renders nothing when nothing waits", () => {
    const { container } = render(<WaitingList items={[]} now={0} onControl={vi.fn()} />);
    expect(container.textContent).toBe("");
  });
});

const ready = (id: string): ApplicationRow =>
  ({
    source_job_id: id,
    company: "Acme",
    role: "Analyst",
    status: "ready",
    preparation_eligible: true,
    job_id: "run-1",
    artifacts: { resume_docx: "r.docx" },
  }) as unknown as ApplicationRow;

describe("ProgressBulkActions beside a running Prepare", () => {
  const bulk = (held: Set<string>, exclusiveBusy = false) => {
    const onFill = vi.fn();
    render(
      <ProgressBulkActions
        selected={[ready("done"), ready("pending")]}
        busy={false}
        exclusiveBusy={exclusiveBusy}
        held={held}
        browserUsable
        onPrepare={vi.fn()}
        onRetailor={vi.fn()}
        onFill={onFill}
      />,
    );
    return onFill;
  };

  it("fills the selected rows the running batch no longer holds", () => {
    const onFill = bulk(new Set(["pending"]));
    const fill = screen.getByRole("button", { name: /^Fill/ });
    expect((fill as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(fill);
    expect(onFill).toHaveBeenCalledWith(["done"]);
  });

  it("waits while Find jobs or the nightly run has Apply to itself", () => {
    bulk(new Set(), true);
    expect((screen.getByRole("button", { name: /^Fill/ }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});
