// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KeyboardShortcuts } from "./KeyboardShortcuts";

// Table columns, filters and the rail layout are read from the profile's settings.
vi.mock("../state/runState", async () => {
  const { DEFAULT_SETTINGS } = await import("../state/runDefaults");
  const setSettings = () => {};
  return { useRunState: () => ({ settings: DEFAULT_SETTINGS, setSettings }) };
});

const desktop = vi.hoisted(() => ({ value: false }));
vi.mock("../lib/useDesktop", () => ({ useDesktop: () => desktop.value }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function page(onSave: () => void) {
  render(
    <MemoryRouter>
      <KeyboardShortcuts />
      <input aria-label="Name" />
      <input aria-label="Filter" data-shortcut="search" />
      <button type="button" data-shortcut="save" onClick={onSave}>
        Save
      </button>
    </MemoryRouter>,
  );
}

describe("KeyboardShortcuts", () => {
  it("Ctrl+S commits the focused field, presses Save, and gives focus back", () => {
    vi.useFakeTimers();
    const onSave = vi.fn();
    page(onSave);
    const name = screen.getByRole("textbox", { name: "Name" });
    name.focus();
    const blur = vi.fn();
    name.addEventListener("blur", blur);
    fireEvent.keyDown(name, { key: "s", ctrlKey: true });
    expect(blur).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
    act(() => vi.runAllTimers());
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(name).toHaveFocus();
  });

  it("Ctrl+F focuses the page's search field in the desktop app only", () => {
    desktop.value = false;
    page(vi.fn());
    const filter = screen.getByRole("textbox", { name: "Filter" });
    expect(fireEvent.keyDown(document.body, { key: "f", ctrlKey: true })).toBe(true);
    expect(filter).not.toHaveFocus();
    cleanup();
    desktop.value = true;
    page(vi.fn());
    const again = screen.getByRole("textbox", { name: "Filter" });
    expect(fireEvent.keyDown(document.body, { key: "f", ctrlKey: true })).toBe(false);
    expect(again).toHaveFocus();
  });
});
