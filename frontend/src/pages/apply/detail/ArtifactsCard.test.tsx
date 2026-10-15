// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ArtifactsCard } from "./ArtifactsCard";

const api = vi.hoisted(() => ({ generateExpansion: vi.fn(), regenerateCoverLetter: vi.fn() }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../api", () => api);
vi.mock("../../../state/confirmState", () => ({ useConfirm: () => ({ confirm }) }));

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderCard(props: Partial<Parameters<typeof ArtifactsCard>[0]> = {}) {
  const onChanged = vi.fn();
  render(
    <ArtifactsCard
      jobId="job1"
      ready
      hasExpansion={false}
      hasCover={false}
      expansionNeeded
      onChanged={onChanged}
      {...props}
    />,
  );
  return onChanged;
}

describe("ArtifactsCard", () => {
  it("generates a missing artifact without asking", async () => {
    api.generateExpansion.mockResolvedValue({});
    const onChanged = renderCard();

    fireEvent.click(screen.getAllByRole("button", { name: "Generate" })[0]);

    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(confirm).not.toHaveBeenCalled();
    expect(api.generateExpansion).toHaveBeenCalledWith("job1", { force: false });
  });

  it("regenerates an existing artifact only after a confirm, skipping the cache", async () => {
    api.generateExpansion.mockResolvedValue({});
    confirm.mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    const onChanged = renderCard({ hasExpansion: true });
    const button = screen.getAllByRole("button", { name: "Regenerate" })[0];

    fireEvent.click(button);
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(api.generateExpansion).not.toHaveBeenCalled();

    fireEvent.click(button);
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(api.generateExpansion).toHaveBeenCalledWith("job1", { force: true });
  });

  it("shows the server's refusal inline and keeps the button usable", async () => {
    api.regenerateCoverLetter.mockRejectedValue(
      new Error("Cannot regenerate while another tailoring run is in progress."),
    );
    renderCard({ hasExpansion: true });

    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    // The 409 reads as the app's plain-language "busy" explanation (`lib/errors.ts`).
    expect(await screen.findByText(/Wait for the current run to finish/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "Generate" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
  });

  it("is disabled until the run has finished, and says when the site doesn't use it", () => {
    renderCard({ ready: false, expansionNeeded: false });
    for (const button of screen.getAllByRole("button")) {
      expect((button as HTMLButtonElement).disabled).toBe(true);
    }
    expect(screen.getByText(/This site doesn't use them/)).toBeTruthy();
  });
});
