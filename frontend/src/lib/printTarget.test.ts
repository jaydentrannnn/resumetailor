// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { currentPrintTarget, printDocument, registerPrintTarget } from "./printTarget";

describe("print targets", () => {
  it("prints the newest document still on screen", () => {
    expect(currentPrintTarget()).toBeNull();
    const dropResume = registerPrintTarget("/resume.pdf");
    const dropTemplate = registerPrintTarget("/template.pdf");
    expect(currentPrintTarget()).toBe("/template.pdf");
    dropTemplate();
    expect(currentPrintTarget()).toBe("/resume.pdf");
    dropResume();
    expect(currentPrintTarget()).toBeNull();
  });

  it("keeps one off-screen print frame", () => {
    printDocument("/a.pdf");
    printDocument("/b.pdf");
    const frames = document.querySelectorAll("iframe#rt-print-frame");
    expect(frames).toHaveLength(1);
    expect(frames[0].getAttribute("src")).toBe("/b.pdf");
  });
});
