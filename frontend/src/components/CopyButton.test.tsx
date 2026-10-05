// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CopyButton } from "./CopyButton";

afterEach(cleanup);

describe("CopyButton consumption callback", () => {
  it("reports only after the clipboard write succeeds", async () => {
    const onCopied = vi.fn();
    let finish!: () => void;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: () => new Promise<void>((resolve) => (finish = resolve)) },
    });
    render(<CopyButton label="Copy skills" text="Python" onCopied={onCopied} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy skills" }));
    expect(onCopied).not.toHaveBeenCalled();
    finish();
    await waitFor(() => expect(onCopied).toHaveBeenCalledOnce());
  });

  it("does not report a failed clipboard and fallback attempt", async () => {
    const onCopied = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const fallback = vi.fn().mockReturnValue(false);
    Object.defineProperty(document, "execCommand", { configurable: true, value: fallback });
    render(<CopyButton label="Copy skills" text="Python" onCopied={onCopied} />);
    fireEvent.click(screen.getByRole("button", { name: "Copy skills" }));
    await waitFor(() => expect(fallback).toHaveBeenCalled());
    expect(onCopied).not.toHaveBeenCalled();
  });
});
