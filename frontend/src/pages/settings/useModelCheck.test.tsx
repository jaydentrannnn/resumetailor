// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { clearModelChecks, useModelCheck } from "./useModelCheck";

const testModel = vi.fn();
vi.mock("../../api", () => ({ testModel: (...args: unknown[]) => testModel(...args) }));

beforeEach(() => {
  vi.useFakeTimers();
  testModel.mockReset().mockResolvedValue({ ok: true, detail: "fine" });
  clearModelChecks();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const settings = { ...DEFAULT_SETTINGS, model: "gemini", model_name: "g-1" };

describe("useModelCheck", () => {
  it("tests once after the model settles, then serves the cached result", async () => {
    const first = renderHook(() => useModelCheck("tailor", settings, true));
    expect(testModel).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(testModel).toHaveBeenCalledTimes(1);
    expect(first.result.current.check).toEqual({ ok: true, detail: "fine" });
    first.unmount();

    const again = renderHook(() => useModelCheck("tailor", settings, true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(testModel).toHaveBeenCalledTimes(1);
    expect(again.result.current.check).toEqual({ ok: true, detail: "fine" });
  });

  it("never tests while not ready (a key is missing)", async () => {
    const { result } = renderHook(() => useModelCheck("tailor", settings, false));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(testModel).not.toHaveBeenCalled();
    expect(result.current.check).toBeNull();
  });

  it("two components on the same model share one call", async () => {
    renderHook(() => useModelCheck("autofill", settings, true));
    renderHook(() => useModelCheck("autofill", settings, true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(testModel).toHaveBeenCalledTimes(1);
    expect(testModel).toHaveBeenCalledWith(settings, "autofill");
  });
});
