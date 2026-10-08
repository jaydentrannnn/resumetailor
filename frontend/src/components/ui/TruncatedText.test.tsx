// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TruncatedText } from "./TruncatedText";

function overflow(cut: boolean) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(cut ? 400 : 100);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(100);
}

describe("TruncatedText", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("is plain text when it fits", () => {
    overflow(false);
    render(<TruncatedText text="Short" />);
    expect(screen.getByText("Short").tagName).toBe("SPAN");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("opens the full text on click and closes on Escape and outside click", () => {
    overflow(true);
    render(<TruncatedText text="A very long error message" label="Error details" />);
    const trigger = screen.getByRole("button", { name: /Error details: A very long/ });
    fireEvent.click(trigger, { clientX: 40, clientY: 50 });
    expect(screen.getByRole("dialog", { name: "Error details" }).textContent).toContain(
      "A very long error message",
    );
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes from the Close button", () => {
    overflow(true);
    render(<TruncatedText text="Long text" />);
    fireEvent.click(screen.getByRole("button", { name: /Show full text/ }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
