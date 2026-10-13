// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { DateParts } from "./DateParts";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => cleanup());

function Harness({
  initial = "",
  ...props
}: { initial?: string } & Partial<React.ComponentProps<typeof DateParts>>) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <DateParts label="Start" value={value} onChange={setValue} {...props} />
      <output data-testid="value">{value}</output>
    </>
  );
}

const out = () => screen.getByTestId("value").textContent;

describe("DateParts", () => {
  it("emits YYYY-MM once a month and a 4-digit year are given", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Start, month"), { target: { value: "6" } });
    expect(out()).toBe("");
    fireEvent.change(screen.getByLabelText("Start, year"), { target: { value: "2027" } });
    expect(out()).toBe("2027-06");
  });

  it("needs a real day when precision is day", () => {
    render(<Harness precision="day" />);
    fireEvent.change(screen.getByLabelText("Start, month"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Start, year"), { target: { value: "2027" } });
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "30" } });
    expect(out()).toBe("");
    expect(screen.getByText("That date doesn't exist.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "14" } });
    expect(out()).toBe("2027-02-14");
  });

  it("shows a stored date in the controls", () => {
    render(<Harness initial="2025-11" />);
    expect((screen.getByLabelText("Start, month") as HTMLSelectElement).value).toBe("11");
    expect((screen.getByLabelText("Start, year") as HTMLInputElement).value).toBe("2025");
  });

  it("offers Present and keeps older free text replaceable", () => {
    const { unmount } = render(<Harness allowPresent />);
    fireEvent.click(screen.getByLabelText("Present"));
    expect(out()).toBe("Present");
    unmount();
    render(<Harness initial="Fall 2022" />);
    expect(screen.getAllByText("Fall 2022").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText("Pick a date instead"));
    expect(out()).toBe("");
    expect(screen.getByLabelText("Start, month")).toBeTruthy();
  });

  it("names the resume value inside the empty controls", () => {
    render(<Harness fallback="June 2027" />);
    expect(screen.getByText("From resume (June 2027)")).toBeTruthy();
    expect((screen.getByLabelText("Start, year") as HTMLInputElement).placeholder).toBe("2027");
  });
});

describe("education optional day", () => {
  it("keeps a completely blank date blank and accepts month/year without inventing a day", () => {
    render(<Harness precision="optional_day" />);
    expect(out()).toBe("");
    const day = screen.getByLabelText("Start, day") as HTMLInputElement;
    expect(day.placeholder).toBe("Day (optional)");
    expect(day.value).toBe("");
    fireEvent.change(screen.getByLabelText("Start, month"), { target: { value: "6" } });
    fireEvent.change(screen.getByLabelText("Start, year"), { target: { value: "2027" } });
    expect(out()).toBe("2027-06");
    expect(day.value).toBe("");
    expect(screen.queryByText("Enter the day.")).toBeNull();
  });

  it("accepts an exact day and returns to month precision when the day is cleared", () => {
    render(<Harness initial="2027-06" precision="optional_day" />);
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "9" } });
    expect(out()).toBe("2027-06-09");
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "" } });
    expect(out()).toBe("2027-06");
  });

  it("validates a supplied day rather than silently discarding an impossible date", () => {
    render(<Harness initial="2024-02" precision="optional_day" />);
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "30" } });
    expect(out()).toBe("");
    expect(screen.getByText("That date doesn't exist.")).toBeTruthy();
    expect(screen.getByLabelText("Start, day").getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(screen.getByLabelText("Start, day"), { target: { value: "29" } });
    expect(out()).toBe("2024-02-29");
    expect(screen.queryByText("That date doesn't exist.")).toBeNull();
  });

  it("reloads exact dates and clears a previous day when a month-only value arrives", () => {
    const onChange = () => undefined;
    const { rerender } = render(
      <DateParts label="Start" value="2027-06-09" precision="optional_day" onChange={onChange} />,
    );
    expect((screen.getByLabelText("Start, day") as HTMLInputElement).value).toBe("09");
    rerender(
      <DateParts label="Start" value="2028-05" precision="optional_day" onChange={onChange} />,
    );
    expect((screen.getByLabelText("Start, day") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("Start, month") as HTMLSelectElement).value).toBe("5");
    expect((screen.getByLabelText("Start, year") as HTMLInputElement).value).toBe("2028");
  });
});
