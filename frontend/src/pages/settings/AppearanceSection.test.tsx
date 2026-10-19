// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { ThemeProvider } from "../../state/themeState";
import { AppearanceSection } from "./AppearanceSection";

// jsdom has no matchMedia; ThemeProvider reads the OS colour scheme through it.
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  addEventListener() {},
  removeEventListener() {},
})) as unknown as typeof window.matchMedia;

afterEach(() => cleanup());

it("switches the theme between System, Light and Dark", () => {
  render(
    <ThemeProvider>
      <AppearanceSection />
    </ThemeProvider>,
  );
  const dark = screen.getByRole("radio", { name: "Dark" });
  fireEvent.click(dark);
  expect(dark.getAttribute("aria-checked")).toBe("true");
  expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
});
