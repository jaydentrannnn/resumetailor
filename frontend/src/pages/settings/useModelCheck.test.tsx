// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { clearModelChecks, useModelCheck } from "./useModelCheck";
import { modelsFor } from "../../lib/aiModels";

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

  it("retests when the custom endpoint changes", async () => {
    const first = {
      ...settings,
      ai_models: {
        ...modelsFor(settings),
        light: {
          provider: "custom" as const,
          model_name: "same",
          api_format: "openai" as const,
          base_url: "https://first.example/v1",
        },
      },
    };
    const hook = renderHook(({ value }) => useModelCheck("light", value, true), {
      initialProps: { value: first },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    hook.rerender({
      value: {
        ...first,
        ai_models: {
          ...first.ai_models,
          light: { ...first.ai_models.light, base_url: "https://second.example/v1" },
        },
      },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(testModel).toHaveBeenCalledTimes(2);
  });

  it("discards a test result from before a credential change", async () => {
    let finish!: (result: { ok: boolean; detail: string }) => void;
    testModel.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const hook = renderHook(() => useModelCheck("light", settings, true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    act(() => clearModelChecks());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(900);
    });
    expect(hook.result.current.check).toEqual({ ok: true, detail: "fine" });
    await act(async () => {
      finish({ ok: false, detail: "old key" });
    });
    expect(hook.result.current.check).toEqual({ ok: true, detail: "fine" });
  });
});
