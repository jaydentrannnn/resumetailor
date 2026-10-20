// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApplyProgress, ApplySettings, PostingTimes } from "../../../api";
import { getApplyProgress } from "../../../api";
import { ProgressBanner } from "./ProgressBanner";
import { ProgressBannerSetting } from "./ProgressBannerSetting";

vi.mock("../../../api", () => ({ getApplyProgress: vi.fn() }));

const today = new Date().toISOString();
const posting = (sent: boolean): PostingTimes => ({
  company: "Acme",
  found_at: today,
  screened_in_at: today,
  tailored_at: today,
  autofilled_at: today,
  sent_at: sent ? today : null,
});

const progress = (fields: Partial<ApplyProgress> = {}): ApplyProgress => ({
  sent: [{ at: today, company: "Acme" }],
  postings: [posting(true), posting(false)],
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

type Banner = Parameters<typeof ProgressBanner>[0]["apply"];
const show = (apply: Banner, onTab = vi.fn(), onSettings = vi.fn()) =>
  render(
    <ProgressBanner
      apply={{ weekly_goal: 10, ...apply }}
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
    show({ progress_banner: "goal" }, onTab, onSettings);
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

  it("counts the chosen stage, and hides the parts switched off", async () => {
    show({
      progress_banner: "goal",
      goal_banner: { counts: "tailored", show_days: false, show_actions: false, compact: true },
    });
    await screen.findByRole("region", { name: "Weekly goal" });
    expect(screen.getByText(/of 10 tailored/)).toBeTruthy();
    expect(screen.queryByRole("list", { name: /each day/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Open Needs you/ })).toBeNull();
  });

  it("draws the activity heatmap for the chosen stage and range", async () => {
    show({ progress_banner: "activity", activity_banner: { counts: "autofilled", range: "4w" } });
    expect(await screen.findByRole("img", { name: /^2 autofilled, last 4 weeks/ })).toBeTruthy();
    cleanup();
    show({ progress_banner: "activity", activity_banner: { compact: true } });
    expect(await screen.findByRole("img", { name: /^sent per week:/ })).toBeTruthy();
  });

  it("shows the pipeline's chosen stages in the chosen style", async () => {
    show({ progress_banner: "pipeline" });
    expect(await screen.findByText("Biggest drop: autofilled to sent.")).toBeTruthy();
    expect(screen.getByText("50% of the postings found were sent.")).toBeTruthy();
    cleanup();
    show({
      progress_banner: "pipeline",
      pipeline_banner: { stages: ["found", "sent"], style: "compact", show_actions: false },
    });
    expect(await screen.findByText("Pipeline · all time")).toBeTruthy();
    expect(screen.queryByText("Tailored")).toBeNull();
    expect(screen.getByText("50% sent")).toBeTruthy();
  });

  it("stays hidden when switched off or before anything was found", async () => {
    const { container } = show({ progress_banner: "off" });
    await waitFor(() => expect(getApplyProgress).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
    cleanup();
    vi.mocked(getApplyProgress).mockClear();
    vi.mocked(getApplyProgress).mockResolvedValue(progress({ found: 0, sent: [], postings: [] }));
    const second = show({ progress_banner: "goal" });
    await waitFor(() => expect(getApplyProgress).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(second.container.innerHTML).toBe("");
  });
});

describe("ProgressBannerSetting", () => {
  it("saves each banner's options merged over the defaults", () => {
    const patch = vi.fn();
    const apply = { progress_banner: "pipeline", weekly_goal: 10 } as ApplySettings;
    render(<ProgressBannerSetting apply={apply} patch={patch} />);
    fireEvent.click(screen.getByRole("radio", { name: "Funnel" }));
    expect(patch.mock.calls[0][0].pipeline_banner).toMatchObject({
      style: "funnel",
      range: "all",
      stages: ["found", "screened_in", "tailored", "autofilled", "sent"],
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Tailored" }));
    expect(patch.mock.calls[1][0].pipeline_banner.stages).toEqual([
      "found",
      "screened_in",
      "autofilled",
      "sent",
    ]);
    fireEvent.click(screen.getByRole("radio", { name: "Custom" }));
    expect(patch.mock.calls[2][0].pipeline_banner.range).toBe("custom");
  });

  it("never lets the pipeline drop below two stages", () => {
    const apply = {
      progress_banner: "pipeline",
      pipeline_banner: { stages: ["found", "sent"] },
    } as ApplySettings;
    render(<ProgressBannerSetting apply={apply} patch={vi.fn()} />);
    expect((screen.getByRole("checkbox", { name: "Found" }) as HTMLInputElement).disabled).toBe(
      true,
    );
    expect((screen.getByRole("checkbox", { name: "Tailored" }) as HTMLInputElement).disabled).toBe(
      false,
    );
  });
});
