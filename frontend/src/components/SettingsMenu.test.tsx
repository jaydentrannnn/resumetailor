// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../state/themeState";
import { SettingsMenu } from "./SettingsMenu";

vi.mock("./workspace/ProfileSwitcher", () => ({ ProfileSwitcher: () => <p>profile switcher</p> }));
vi.mock("../state/workspaceState", () => ({
  useWorkspaceState: () => ({
    workspaces: [{ id: "w1", label: "Alex" }],
    activeId: "w1",
    switching: false,
  }),
}));

afterEach(() => cleanup());
// jsdom has no matchMedia; ThemeProvider reads the OS colour scheme through it.
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  addEventListener() {},
  removeEventListener() {},
})) as unknown as typeof window.matchMedia;

function renderMenu() {
  return render(
    <ThemeProvider>
      <SettingsMenu />
      <p>outside</p>
    </ThemeProvider>,
  );
}

describe("SettingsMenu", () => {
  it("names the active profile and opens the profile and theme settings", () => {
    renderMenu();
    const button = screen.getByRole("button", { name: /Alex/ });
    expect(screen.queryByText("profile switcher")).toBeNull();
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("profile switcher")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(screen.getByRole("radio", { name: "Dark" }).getAttribute("aria-checked")).toBe("true");
  });

  it("closes on Escape and on a click outside, but not while a modal is open", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Alex/ }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("profile switcher")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Alex/ }));
    const modal = document.createElement("div");
    modal.setAttribute("aria-modal", "true");
    document.body.append(modal);
    fireEvent.mouseDown(modal);
    expect(screen.getByText("profile switcher")).toBeTruthy();
    modal.remove();
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByText("profile switcher")).toBeNull();
  });
});
