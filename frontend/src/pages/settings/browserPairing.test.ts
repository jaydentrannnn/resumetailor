import { describe, expect, it } from "vitest";
import { pairingCountdown, pairingDate, secondsRemaining } from "./browserPairing";

describe("browser pairing time", () => {
  it("uses the wall clock and expires after a suspended tab resumes", () => {
    const expires = 120_000;
    expect(secondsRemaining(expires, 0)).toBe(120);
    expect(secondsRemaining(expires, 119_001)).toBe(1);
    expect(secondsRemaining(expires, 130_000)).toBe(0);
  });

  it("formats countdown and invalid dates", () => {
    expect(pairingCountdown(120)).toBe("2:00");
    expect(pairingCountdown(9)).toBe("0:09");
    expect(pairingDate("bad")).toBe("Unknown");
  });
});
