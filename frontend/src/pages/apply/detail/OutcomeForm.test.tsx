// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { OutcomeForm } from "./OutcomeForm";

afterEach(cleanup);

it("requires an employer deadline before recording a timeline", () => {
  const onSubmit = vi.fn();
  render(<OutcomeForm editing={null} busy={false} onSubmit={onSubmit} onCancel={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("What happened"), {
    target: { value: "employer_timeline" },
  });
  const deadline = screen.getByLabelText("Expected reply date") as HTMLInputElement;
  expect(deadline.required).toBe(true);
  expect(deadline.checkValidity()).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Record" }));
  expect(onSubmit).not.toHaveBeenCalled();

  fireEvent.change(deadline, { target: { value: "2026-10-30" } });
  fireEvent.click(screen.getByRole("button", { name: "Record" }));
  expect(onSubmit).toHaveBeenCalledWith({
    type: "employer_timeline",
    occurred_on: "2026-10-30",
    note: "",
  });

  fireEvent.change(screen.getByLabelText("What happened"), { target: { value: "offer" } });
  const optional = screen.getByLabelText("When (optional)") as HTMLInputElement;
  fireEvent.change(optional, { target: { value: "" } });
  expect(optional.required).toBe(false);
  expect(optional.checkValidity()).toBe(true);
});
