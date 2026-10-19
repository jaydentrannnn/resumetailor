import { describe, expect, it } from "vitest";
import { viewerSrc } from "./viewer";

describe("viewer", () => {
  it("frames the PDF to its width and hides the PDF viewer's own chrome", () => {
    expect(viewerSrc("/a.pdf")).toBe("/a.pdf#toolbar=0&navpanes=0&view=FitH");
    expect(viewerSrc("/a.pdf?v=2")).toBe("/a.pdf?v=2#toolbar=0&navpanes=0&view=FitH");
  });
});
