import { describe, expect, it } from "vitest";
import { applicationStatusTone } from "./applicationStatus";

describe("applicationStatusTone", () => {
  it("groups statuses by what the user needs to do next", () => {
    expect(applicationStatusTone("ready")).toBe("accent");
    expect(applicationStatusTone("awaiting_review")).toBe("warn");
    expect(applicationStatusTone("submit_unconfirmed")).toBe("warn");
    expect(applicationStatusTone("fill_failed")).toBe("danger");
    expect(applicationStatusTone("submitted")).toBe("success");
    expect(applicationStatusTone("tailoring")).toBe("info");
  });
  it("falls back to neutral for early and unknown statuses", () => {
    expect(applicationStatusTone("discovered")).toBe("neutral");
    expect(applicationStatusTone("something_new")).toBe("neutral");
  });
});
