// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SubmissionAttempt } from "../../../api";
import { SentAttempts } from "./SentAttempts";

function attempt(patch: Partial<SubmissionAttempt> = {}): SubmissionAttempt {
  return {
    id: "a1",
    number: 2,
    submitted_at: "2026-10-26T12:00:00Z",
    method: "auto",
    confirmed: true,
    snapshot_dir: "",
    files: { "attached/resume.pdf": "abc", "tailored.pdf": "def", "jd.txt": "123" },
    attached: { "attached/resume.pdf": "abc" },
    voided_at: null,
    error: "",
    ...patch,
  };
}

describe("SentAttempts", () => {
  afterEach(cleanup);

  it("separates what the app attached from the prepared files, each opening its copy", () => {
    render(<SentAttempts applicationId="row 1" attempts={[attempt()]} />);
    const resume = screen.getByRole("link", { name: "resume.pdf" });
    expect(resume.getAttribute("href")).toBe(
      "/api/applications/row%201/attempts/2/files/attached/resume.pdf",
    );
    expect(resume.closest("p")?.textContent).toMatch(/^Attached by the app:/);
    expect(screen.getByRole("link", { name: "tailored.pdf" }).closest("p")?.textContent).toMatch(
      /^Prepared files:/,
    );
  });

  it("names what each attached file was for, so two of one name stay apart", () => {
    const both = {
      "attached/transcript/document.pdf": "a",
      "attached/portfolio/document.pdf": "b",
    };
    render(
      <SentAttempts applicationId="r" attempts={[attempt({ files: both, attached: both })]} />,
    );
    expect(
      screen.getByRole("link", { name: "document.pdf (transcript)" }).getAttribute("href"),
    ).toBe("/api/applications/r/attempts/2/files/attached/transcript/document.pdf");
    expect(screen.getByRole("link", { name: "document.pdf (portfolio)" })).toBeTruthy();
  });

  it("says a manual mark's files were not confirmed attached", () => {
    render(
      <SentAttempts
        applicationId="r"
        attempts={[attempt({ method: "manual", confirmed: false, attached: {} })]}
      />,
    );
    expect(screen.getByText(/Prepared files \(not confirmed attached\)/)).toBeTruthy();
  });
});
