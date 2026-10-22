// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { ResumeQuality } from "../lib/resumeQuality";
import { ResumeQualityNotice } from "./ResumeQualityNotice";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(cleanup);

const base: ResumeQuality = {
  fill_ratio: 0.95,
  fill_target: 0.93,
  estimated: false,
  verified: true,
  missing_sections: [],
};
const EMAIL =
  "Your email address isn't in the PDF's text, so an applicant tracking system can't read it.";

it("lists PDF text issues with PDF-specific advice", () => {
  render(
    <ResumeQualityNotice
      quality={{ ...base, pdf_text: { status: "issues", issues: [EMAIL], advisories: [] } }}
    />,
  );
  expect(screen.getByRole("alert").textContent).toContain(EMAIL);
  expect(screen.getByText(/copy its text to see what an application site reads/)).toBeTruthy();
  expect(screen.queryByText(/choose a template that supports these sections/)).toBeNull();
});

it("shows an unchecked PDF as a quiet note, not an alert", () => {
  const note = "The PDF's text couldn't be read back, so it wasn't checked.";
  render(
    <ResumeQualityNotice
      quality={{ ...base, pdf_text: { status: "unverified", issues: [], advisories: [note] } }}
    />,
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByText(note)).toBeTruthy();
});

it("renders nothing for a verified PDF or a run from before the check", () => {
  const { container, rerender } = render(
    <ResumeQualityNotice
      quality={{ ...base, pdf_text: { status: "verified", issues: [], advisories: [] } }}
    />,
  );
  expect(container.innerHTML).toBe("");
  rerender(<ResumeQualityNotice quality={base} />);
  expect(container.innerHTML).toBe("");
});
