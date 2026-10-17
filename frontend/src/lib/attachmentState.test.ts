import { describe, expect, it } from "vitest";
import { attachmentStateLabel } from "./attachmentState";

describe("attachment state label", () => {
  it("says a file the fill uploaded was uploaded", () => {
    expect(attachmentStateLabel({ verified: true })).toBe("uploaded and verified");
    expect(attachmentStateLabel({ state: "verified" })).toBe("uploaded and verified");
  });
  it("never calls a file found on the form verified", () => {
    expect(attachmentStateLabel({ state: "kept_existing", verified: true })).toBe(
      "kept the file already attached",
    );
    expect(attachmentStateLabel({ verified: true, preserved: true })).toBe(
      "kept the file already attached",
    );
    expect(attachmentStateLabel({ state: "preserved" })).toBe("kept the file already attached");
    expect(
      attachmentStateLabel({ state: "preserved", verified: true, uploaded_by_app: true }),
    ).toBe("uploaded by an earlier fill");
  });
  it("names other states as recorded", () => {
    expect(attachmentStateLabel({ state: "not_requested" })).toBe("not requested");
    expect(attachmentStateLabel({ verified: false })).toBe("unverified");
  });
});
