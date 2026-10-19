import { describe, expect, it } from "vitest";
import { stepZoom, viewerSrc } from "./viewer";

describe("viewer", () => {
  it("frames the PDF through its URL fragment", () => {
    expect(viewerSrc("/a.pdf", "width")).toBe("/a.pdf#toolbar=0&navpanes=0&view=FitH");
    expect(viewerSrc("/a.pdf", "page")).toBe("/a.pdf#toolbar=0&navpanes=0&view=Fit");
    expect(viewerSrc("/a.pdf?v=2", 125)).toBe("/a.pdf?v=2#toolbar=0&navpanes=0&zoom=125");
  });

  it("steps zoom from a fit at 100% and stops at the ends", () => {
    expect(stepZoom("width", 1)).toBe(110);
    expect(stepZoom("page", -1)).toBe(90);
    expect(stepZoom(200, 1)).toBe(200);
    expect(stepZoom(50, -1)).toBe(50);
  });
});
