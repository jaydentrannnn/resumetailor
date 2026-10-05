// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GenerateExperienceCard } from "./GenerateExperienceCard";

const generate = vi.hoisted(() => vi.fn());
vi.mock("../api", () => ({ generateExpansion: generate }));

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => {
  cleanup();
  generate.mockReset();
});

const expansion = { entries: [], warnings: [], model: "m", char_limit: 2000 };

describe("GenerateExperienceCard", () => {
  it("generates the run's expansion and hands it up", async () => {
    generate.mockResolvedValue(expansion);
    const onGenerated = vi.fn();
    render(<GenerateExperienceCard jobId="job1" ready onGenerated={onGenerated} />);

    fireEvent.click(screen.getByRole("button", { name: "Generate application experience" }));

    await vi.waitFor(() => expect(onGenerated).toHaveBeenCalledWith(expansion));
    expect(generate).toHaveBeenCalledWith("job1");
  });

  it("shows the error and keeps the button usable", async () => {
    generate.mockRejectedValue(new Error("This job has no saved bullets."));
    render(<GenerateExperienceCard jobId="job1" ready onGenerated={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Generate application experience" }));

    expect(await screen.findByText(/no saved bullets/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "Generate application experience" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("is disabled while another run is busy", () => {
    render(<GenerateExperienceCard jobId="job1" ready={false} onGenerated={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Generate application experience" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });
});
