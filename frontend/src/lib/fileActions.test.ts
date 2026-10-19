import { describe, expect, it } from "vitest";
import { downloadFilename, openLabel, saveLabel } from "./fileActions";

describe("downloadFilename", () => {
  it("reads quoted, bare and RFC 5987 names", () => {
    expect(downloadFilename('attachment; filename="Acme Resume.pdf"', "x")).toBe("Acme Resume.pdf");
    expect(downloadFilename("attachment; filename=resume.docx", "x")).toBe("resume.docx");
    expect(
      downloadFilename(
        "attachment; filename=\"Caf_.pdf\"; filename*=UTF-8''Caf%C3%A9%20Resume.pdf",
        "x",
      ),
    ).toBe("Café Resume.pdf");
  });

  it("falls back when the header names nothing usable", () => {
    expect(downloadFilename(null, "resume.pdf")).toBe("resume.pdf");
    expect(downloadFilename("inline", "resume.pdf")).toBe("resume.pdf");
    expect(downloadFilename("attachment; filename*=UTF-8''%E0%A4%A", "a.pdf")).toBe("a.pdf");
  });
});

describe("labels", () => {
  it("say Save… on desktop and Download in the browser", () => {
    expect(saveLabel("PDF", true)).toBe("Save PDF…");
    expect(saveLabel("PDF", false)).toBe("Download PDF");
    expect(openLabel("resume-docx")).toBe("Open in Word");
    expect(openLabel("cover-pdf")).toBe("Open");
  });
});
