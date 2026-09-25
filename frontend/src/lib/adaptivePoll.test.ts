import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BUSY_POLL_MS, IDLE_POLL_MS, nextPollDelay, startAdaptivePoll } from "./adaptivePoll";

class FakeDoc {
  visibilityState: DocumentVisibilityState = "visible";
  private listeners: (() => void)[] = [];
  addEventListener(_type: string, fn: () => void) {
    this.listeners.push(fn);
  }
  removeEventListener(_type: string, fn: () => void) {
    this.listeners = this.listeners.filter((l) => l !== fn);
  }
  set(state: DocumentVisibilityState) {
    this.visibilityState = state;
    this.listeners.forEach((l) => l());
  }
}

describe("nextPollDelay", () => {
  it("backs off when idle and pauses when hidden", () => {
    expect(nextPollDelay(true, false)).toBe(BUSY_POLL_MS);
    expect(nextPollDelay(false, false)).toBe(IDLE_POLL_MS);
    expect(nextPollDelay(true, true)).toBeNull();
  });
});

describe("startAdaptivePoll", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("polls fast while busy and slowly once idle", async () => {
    let busy = true;
    const tick = vi.fn(async () => busy);
    const doc = new FakeDoc();
    const { stop } = startAdaptivePoll(tick, doc as unknown as Document);
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(BUSY_POLL_MS);
    expect(tick).toHaveBeenCalledTimes(2);
    busy = false;
    await vi.advanceTimersByTimeAsync(BUSY_POLL_MS);
    expect(tick).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(IDLE_POLL_MS - 1);
    expect(tick).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(1);
    expect(tick).toHaveBeenCalledTimes(4);
    stop();
  });

  it("makes no requests while hidden and polls at once when shown", async () => {
    const tick = vi.fn(async () => true);
    const doc = new FakeDoc();
    const { stop } = startAdaptivePoll(tick, doc as unknown as Document);
    await vi.advanceTimersByTimeAsync(0);
    doc.set("hidden");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(tick).toHaveBeenCalledTimes(1);
    doc.set("visible");
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("wake polls immediately instead of waiting out the idle delay", async () => {
    const tick = vi.fn(async () => false);
    const { stop, wake } = startAdaptivePoll(tick, new FakeDoc() as unknown as Document);
    await vi.advanceTimersByTimeAsync(0);
    wake();
    await vi.advanceTimersByTimeAsync(0);
    expect(tick).toHaveBeenCalledTimes(2);
    stop();
  });

  it("stops for good", async () => {
    const tick = vi.fn(async () => true);
    const { stop } = startAdaptivePoll(tick, new FakeDoc() as unknown as Document);
    await vi.advanceTimersByTimeAsync(0);
    stop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(tick).toHaveBeenCalledTimes(1);
  });
});
