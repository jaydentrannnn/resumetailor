// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../state/themeState";
import { ProfileMenu } from "./ProfileMenu";
import { ThemeButton } from "./ThemeButton";

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
      <ProfileMenu />
      <ThemeButton />
      <p>outside</p>
    </ThemeProvider>,
  );
}

describe("ProfileMenu", () => {
  it("names the active profile and opens the profile switcher", () => {
    renderMenu();
    const button = screen.getByRole("button", { name: /Alex/ });
    expect(screen.queryByText("profile switcher")).toBeNull();
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("profile switcher")).toBeTruthy();
  });

  it("the theme button cycles System, Light, Dark and names the current mode", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Theme: System/ }));
    fireEvent.click(screen.getByRole("button", { name: /Theme: Light/ }));
    expect(screen.getByRole("button", { name: /Theme: Dark\. Switch to System/ })).toBeTruthy();
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
