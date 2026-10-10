// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SectionBalanceBar } from "./SectionBalanceBar";

const sections = [
  { id: "work", title: "Work", kind: "experience" },
  { id: "lab", title: "Lab", kind: "experience" },
  { id: "proj", title: "Projects", kind: "project" },
];

afterEach(cleanup);

describe("SectionBalanceBar", () => {
  it("renders one divider per neighbouring pair and a legend", () => {
    render(<SectionBalanceBar sections={sections} shares={[50, 25, 25]} onChange={() => {}} />);
    expect(screen.getAllByRole("slider")).toHaveLength(2);
    expect(screen.getByText("about 50%")).toBeTruthy();
  });

  it("arrow keys trade 5% between the two neighbours only", () => {
    const onChange = vi.fn();
    render(<SectionBalanceBar sections={sections} shares={[50, 25, 25]} onChange={onChange} />);
    const second = screen.getByRole("slider", { name: "Between Lab and Projects" });
    fireEvent.keyDown(second, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith([50, 30, 20]);
    fireEvent.keyDown(second, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith([50, 5, 45]);
  });

  it("does not report a move past the 5% minimum", () => {
    const onChange = vi.fn();
    render(<SectionBalanceBar sections={sections} shares={[5, 70, 25]} onChange={onChange} />);
    fireEvent.keyDown(screen.getByRole("slider", { name: "Between Work and Lab" }), {
      key: "ArrowLeft",
    });
    expect(onChange).not.toHaveBeenCalled();
  });
});
