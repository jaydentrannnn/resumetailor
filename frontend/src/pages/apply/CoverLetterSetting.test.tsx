// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CoverLetterSetting } from "./CoverLetterSetting";

afterEach(cleanup);

describe("CoverLetterSetting", () => {
  it("shows the four choices and explains the selected one", () => {
    render(<CoverLetterSetting value="every" onChange={() => {}} />);
    const radios = screen.getAllByRole("radio").map((radio) => radio.textContent);
    expect(radios).toEqual(["Off", "Required only", "Required and optional", "Every application"]);
    expect(
      screen.getByRole("radio", { name: "Every application" }).getAttribute("aria-checked"),
    ).toBe("true");
    expect(screen.getByText(/while preparing every application/)).toBeTruthy();
  });

  it("reports the picked mode", () => {
    const onChange = vi.fn();
    render(<CoverLetterSetting value="required" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: "Required and optional" }));
    expect(onChange).toHaveBeenCalledWith("optional");
  });
});
