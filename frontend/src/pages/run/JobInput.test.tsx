// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchJdFromUrl, type JdText } from "../../api";
import { JobInput } from "./JobInput";

vi.mock("../../api", () => ({ fetchJdFromUrl: vi.fn(), extractJdFile: vi.fn() }));

afterEach(cleanup);

describe("JobInput link fetch", () => {
  it("drops a fetch still running once you switch back to pasting", async () => {
    let finish: (result: JdText) => void = () => {};
    let signal: AbortSignal | undefined;
    vi.mocked(fetchJdFromUrl).mockImplementation((_url, given) => {
      signal = given;
      return new Promise((resolve) => (finish = resolve));
    });
    const setJdText = vi.fn();
    render(<JobInput jdText="My own notes" setJdText={setJdText} disabled={false} />);
    fireEvent.click(screen.getByRole("tab", { name: "From a link" }));
    fireEvent.change(screen.getByLabelText(/Link to the posting/), {
      target: { value: "https://jobs.example.com/1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Get posting" }));
    expect(screen.getByLabelText(/Link to the posting/)).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    expect(signal?.aborted).toBe(true);
    await act(async () => finish({ text: "Late posting", warnings: [], final_url: "" } as JdText));
    expect(setJdText).not.toHaveBeenCalled();
  });
});
