// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BrowserStatus } from "../../api";
import { browserView } from "../../lib/browserState";
import { BrowserPicker, ConnectionStatus } from "./BrowserConnection";

afterEach(cleanup);

const status = (fields: Partial<BrowserStatus> = {}): BrowserStatus => ({
  reachable: false,
  browser: "",
  user_agent: "",
  error: "",
  cdp_url: "http://127.0.0.1:9222",
  state: "idle",
  reason: "",
  can_launch: true,
  docker: false,
  installed: { edge: true, chrome: true, comet: false },
  selected: null,
  resolved: "edge",
  ...fields,
});

function renderPicker(current: BrowserStatus, onSelect = vi.fn(), run = vi.fn()) {
  render(
    <BrowserPicker
      status={current}
      view={browserView(current, null)}
      selected={null}
      onSelect={onSelect}
      launch={{ run, busy: false }}
    />,
  );
  return { onSelect, run };
}

describe("BrowserPicker", () => {
  it("greys out browsers that aren't installed and selects the automatic pick", () => {
    renderPicker(status());
    expect((screen.getByRole("radio", { name: /Comet/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("radio", { name: "Edge" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByText(/remote-debugging-port/)).toBeNull();
  });

  it("saves a choice and launches on request", () => {
    const { onSelect, run } = renderPicker(status());
    fireEvent.click(screen.getByRole("radio", { name: "Chrome" }));
    expect(onSelect).toHaveBeenCalledWith("chrome");
    fireEvent.click(screen.getByRole("button", { name: "Launch now" }));
    expect(run).toHaveBeenCalled();
  });

  it("shows only the manual flag in Docker", () => {
    renderPicker(status({ docker: true, can_launch: false }));
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByText("--remote-debugging-port=9222")).toBeTruthy();
  });
});

describe("ConnectionStatus", () => {
  it.each([
    [status({ reachable: true }), "Browser ready"],
    [status(), "Launches when needed"],
    [status({ installed: {} }), "Browser not available"],
  ])("labels the state", (current, label) => {
    render(<ConnectionStatus view={browserView(current, null)} />);
    expect(screen.getByText(label)).toBeTruthy();
  });
});
