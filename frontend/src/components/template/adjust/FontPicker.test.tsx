// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FontPicker } from "./FontPicker";

const FONTS = {
  families: ["Arial", "Calibri", "Garamond", "Georgia"],
  common: ["Calibri", "Georgia"],
};

afterEach(cleanup);

function setup(value = "Calibri", fonts = FONTS) {
  const onChange = vi.fn();
  render(
    <>
      <span id="lbl">Typeface</span>
      <FontPicker value={value} fonts={fonts} labelId="lbl" onChange={onChange} />
    </>,
  );
  return { onChange, box: screen.getByRole("combobox", { name: "Typeface" }) };
}

it("filters as you type and picks with Enter", () => {
  const { onChange, box } = setup();
  fireEvent.focus(box);
  expect(box.getAttribute("aria-expanded")).toBe("true");
  fireEvent.change(box, { target: { value: "gar" } });
  expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Garamond"]);
  fireEvent.keyDown(box, { key: "Enter" });
  expect(onChange).toHaveBeenCalledWith("Garamond");
});

it("moves with the arrows and closes on Escape", () => {
  const { onChange, box } = setup();
  fireEvent.focus(box);
  fireEvent.change(box, { target: { value: "" } });
  fireEvent.keyDown(box, { key: "ArrowDown" });
  const active = box.getAttribute("aria-activedescendant");
  expect(active && document.getElementById(active)?.textContent).toBe("Georgia");
  fireEvent.keyDown(box, { key: "Escape" });
  expect(box.getAttribute("aria-expanded")).toBe("false");
  expect(onChange).not.toHaveBeenCalled();
});

it("says when the font is not installed here", () => {
  setup("Helvetica Neue");
  expect(screen.getByText(/Not installed here/)).toBeTruthy();
});
