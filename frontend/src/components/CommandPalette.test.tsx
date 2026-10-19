// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Command } from "../lib/commands";
import { CommandProvider, useCommands } from "../state/commandState";
import { CommandPalette } from "./CommandPalette";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function Page({ onSave }: { onSave: () => void }) {
  const [saved, setSaved] = useState(false);
  useCommands((): Command[] => [
    { id: "save", title: "Save resume", group: "Resume", shortcut: ["Ctrl", "S"], run: onSave },
    {
      id: "saved",
      title: "Mark saved",
      group: "Resume",
      disabled: saved,
      run: () => setSaved(true),
    },
    { id: "go", title: "Template", group: "Go to", run: () => {} },
  ]);
  return <button type="button">Elsewhere</button>;
}

function open() {
  fireEvent.keyDown(document.body, { key: "k", ctrlKey: true });
  return screen.getByRole("combobox", { name: "Find a page or an action" });
}

describe("CommandPalette", () => {
  it("lists the page's commands, filters as you type, and runs the highlighted one", () => {
    vi.useFakeTimers();
    const onSave = vi.fn();
    render(
      <CommandProvider>
        <Page onSave={onSave} />
        <CommandPalette />
      </CommandProvider>,
    );
    const input = open();
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Save resumeResumeCtrlS",
      "Mark savedResume",
      "TemplateGo to",
    ]);
    fireEvent.change(input, { target: { value: "temp" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => vi.runAllTimers());
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("reads the page's state when it opens and gives focus back on Escape", () => {
    vi.useFakeTimers();
    render(
      <CommandProvider>
        <Page onSave={() => {}} />
        <CommandPalette />
      </CommandProvider>,
    );
    const elsewhere = screen.getByRole("button", { name: "Elsewhere" });
    elsewhere.focus();
    open();
    fireEvent.click(screen.getByRole("option", { name: /Mark saved/ }));
    act(() => vi.runAllTimers());
    expect(elsewhere).toHaveFocus();
    const input = open();
    expect(screen.queryByRole("option", { name: /Mark saved/ })).not.toBeInTheDocument();
    expect(input).toHaveFocus();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(elsewhere).toHaveFocus();
  });
});
