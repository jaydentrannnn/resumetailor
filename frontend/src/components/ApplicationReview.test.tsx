// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicationRow } from "../api";
import { ApplicationReview } from "./ApplicationReview";

afterEach(cleanup);

const outcome = (id: string, state: string) => ({
  step_id: id,
  frame_id: "",
  field_id: id,
  label: `Field ${id}`,
  state,
  value: "x",
});

const application = (states: string[]) =>
  ({
    status: "awaiting_review",
    fill: { field_outcomes: states.map((state, i) => outcome(String(i), state)) },
  }) as unknown as ApplicationRow;

function show(states: string[]) {
  return (
    <ApplicationReview
      application={application(states)}
      disabled={false}
      onRefresh={vi.fn()}
      onCorrect={vi.fn()}
    />
  );
}

describe("ApplicationReview", () => {
  it("falls back to every field when the selected group empties", () => {
    const { rerender } = render(show(["failed", "verified_filled"]));
    const attention = screen.getByRole("radio", { name: /Needs attention/ });
    fireEvent.click(attention);
    expect(attention.getAttribute("aria-checked")).toBe("true");
    // The last field needing attention was corrected.
    rerender(show(["verified_filled", "verified_filled"]));
    expect(screen.queryByRole("radio", { name: /Needs attention/ })).toBeNull();
    const all = screen.getByRole("radio", { name: /All recorded fields/ });
    expect(all.getAttribute("aria-checked")).toBe("true");
    expect(all.getAttribute("tabindex")).toBe("0");
    expect(screen.getAllByText(/Field \d/)).toHaveLength(2);
  });

  it("pages the field list from above and below", () => {
    render(show(["failed"]));
    expect(screen.getAllByLabelText("Rows per page")).toHaveLength(2);
  });
});
