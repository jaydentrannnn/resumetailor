// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChoiceOrOther } from "./ChoiceOrOther";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => cleanup());

const props = { id: "x", label: "Race", onChange: () => {} };

describe("ChoiceOrOther", () => {
  it("selects a listed value once the options arrive after the first render", () => {
    const { rerender } = render(<ChoiceOrOther {...props} value="Asian" options={[]} />);
    rerender(<ChoiceOrOther {...props} value="Asian" options={["Asian", "White"]} />);
    expect((screen.getByLabelText("Race") as HTMLSelectElement).value).toBe("Asian");
    expect(screen.queryByLabelText("Race, other")).toBeNull();
  });

  it("keeps a value outside the list as Other", () => {
    render(<ChoiceOrOther {...props} value="Pacific" options={["Asian"]} />);
    expect((screen.getByLabelText("Race") as HTMLSelectElement).value).toBe("__other__");
    expect((screen.getByLabelText("Race, other") as HTMLInputElement).value).toBe("Pacific");
  });

  it("opens an empty text box when Other is picked", () => {
    render(<ChoiceOrOther {...props} value="" options={["Asian"]} />);
    fireEvent.change(screen.getByLabelText("Race"), { target: { value: "__other__" } });
    expect(screen.getByLabelText("Race, other")).toBeTruthy();
  });
});
