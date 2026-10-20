// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyProgress, ProgressBanner as BannerKind } from "../../../api";
import { getApplyProgress } from "../../../api";
import { ProgressBanner } from "./ProgressBanner";

vi.mock("../../../api", () => ({ getApplyProgress: vi.fn() }));

const progress = (fields: Partial<ApplyProgress> = {}): ApplyProgress => ({
  sent: [{ at: new Date().toISOString(), company: "Acme" }],
  found: 198,
  screened_in: 54,
  tailored: 52,
  autofilled: 50,
  sent_total: 28,
  needs_you: 21,
  ready: 2,
  unscreened: 104,
  ...fields,
});

beforeEach(() => vi.mocked(getApplyProgress).mockResolvedValue(progress()));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const show = (kind: BannerKind, onTab = vi.fn(), onSettings = vi.fn()) =>
  render(
    <ProgressBanner
      kind={kind}
      goal={10}
      workspaceId="w"
      revision={0}
      onTab={onTab}
      onSettings={onSettings}
    />,
  );

describe("ProgressBanner", () => {
  it("shows this week against the goal and opens the work it points at", async () => {
    const onTab = vi.fn();
    const onSettings = vi.fn();
    show("goal", onTab, onSettings);
    expect(await screen.findByRole("region", { name: "Weekly goal" })).toBeTruthy();
    expect(
      screen.getByRole("progressbar", { name: "Weekly goal" }).getAttribute("aria-valuenow"),
    ).toBe("10");
    expect(screen.getByText("2 are ready to fill and 21 are waiting on you.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open Needs you (21)" }));
    fireEvent.click(screen.getByRole("button", { name: "See 2 ready to fill" }));
    expect(onTab.mock.calls).toEqual([["needs"], ["progress"]]);
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(onSettings).toHaveBeenCalled();
  });

  it("draws the activity heatmap and the pipeline's biggest drop", async () => {
    show("activity");
    expect(await screen.findByRole("img", { name: /^1 sent in the last 13 weeks/ })).toBeTruthy();
    cleanup();
    show("pipeline");
    expect(await screen.findByText("Biggest drop: found to screened in.")).toBeTruthy();
    expect(screen.getByText("14% of the postings found were sent.")).toBeTruthy();
  });

  it("stays hidden when switched off or before anything was found", async () => {
    const { container } = show("off");
    await waitFor(() => expect(getApplyProgress).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
    cleanup();
    vi.mocked(getApplyProgress).mockClear();
    vi.mocked(getApplyProgress).mockResolvedValue(progress({ found: 0, sent: [] }));
    const second = show("goal");
    await waitFor(() => expect(getApplyProgress).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(second.container.innerHTML).toBe("");
  });
});
