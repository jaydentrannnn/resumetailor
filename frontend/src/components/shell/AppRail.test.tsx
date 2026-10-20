// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { AppRail } from "./AppRail";

const state = vi.hoisted(() => ({ hints: undefined as boolean | undefined }));
vi.mock("../../lib/useDesktop", () => ({ useDesktop: () => true }));
vi.mock("../../state/runState", () => ({
  useRunState: () => ({ settings: { show_shortcut_hints: state.hints } }),
}));
vi.mock("./useNeedsYouCount", () => ({ useNeedsYouCount: () => 21 }));
vi.mock("../ProfileMenu", () => ({ ProfileMenu: () => null }));
vi.mock("../SetupHealth", () => ({ SetupHealth: () => null }));
vi.mock("../UpdateChip", () => ({ UpdateChip: () => null }));
vi.mock("../../state/themeState", () => ({
  useTheme: () => ({ preference: "system", setPreference: () => {} }),
}));

afterEach(cleanup);

const rail = () =>
  render(
    <MemoryRouter>
      <AppRail />
    </MemoryRouter>,
  );

it("shows the desktop shortcut hints unless they are switched off", () => {
  rail();
  const hint = screen.getByText("Ctrl 2");
  // Never wraps beside the Needs-you count.
  expect(hint.className).toContain("whitespace-nowrap");
  cleanup();
  state.hints = false;
  rail();
  expect(screen.queryByText("Ctrl 2")).toBeNull();
  expect(screen.queryByText("Ctrl ,")).toBeNull();
});
