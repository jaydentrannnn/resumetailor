import { describe, expect, it } from "vitest";
import { applicationStatusTone } from "./applicationStatus";

describe("applicationStatusTone", () => {
  it("groups statuses by what the user needs to do next", () => {
    expect(applicationStatusTone("ready")).toBe("ready");
    expect(applicationStatusTone("awaiting_review")).toBe("attention");
    expect(applicationStatusTone("submit_unconfirmed")).toBe("attention");
    expect(applicationStatusTone("fill_failed")).toBe("failed");
    expect(applicationStatusTone("submitted")).toBe("done");
    expect(applicationStatusTone("tailoring")).toBe("live");
  });
  it("maps every pipeline status to its tone", () => {
    expect(applicationStatusTone("filling")).toBe("live");
    expect(applicationStatusTone("interview")).toBe("done");
    expect(applicationStatusTone("needs_browser")).toBe("attention");
    expect(applicationStatusTone("awaiting_otp")).toBe("attention");
    expect(applicationStatusTone("tailor_failed")).toBe("failed");
    expect(applicationStatusTone("rejected")).toBe("muted");
    expect(applicationStatusTone("ghosted")).toBe("muted");
  });
  it("falls back to neutral for early and unknown statuses", () => {
    expect(applicationStatusTone("discovered")).toBe("neutral");
    expect(applicationStatusTone("something_new")).toBe("neutral");
  });
});
