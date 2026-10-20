// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { CoverLetter } from "../api";
import { DocumentsCard } from "./DocumentsCard";

vi.mock("../api", () => {
  const url = (name: string) => (id: string) => `/${id}/${name}`;
  return {
    fetchConfig: vi.fn().mockResolvedValue({ desktop: false }),
    regenerateCoverLetter: vi.fn(),
    coverLetterDocxUrl: url("cover.docx"),
    coverLetterMdUrl: url("cover.md"),
    coverLetterPdfUrl: url("cover.pdf"),
    coverLetterPreviewUrl: url("cover-preview.pdf"),
    downloadPdfUrl: url("resume.pdf"),
    downloadUrl: url("resume.docx"),
    previewUrl: url("preview.pdf"),
  };
});
vi.mock("./viewer/DocumentViewer", () => ({ DocumentViewer: () => <p>viewer</p> }));

afterEach(cleanup);

const letter: CoverLetter = {
  company: "Acme",
  company_location: "",
  addressee: "",
  paragraphs: ["Dear team, I build things."],
  salutation: "Dear team,",
  closing: "Best,",
  signature: "A",
  inside_address: [],
  date: "",
  warnings: ["Dropped a claim the resume does not support."],
  model: "m",
  word_count: 5,
  has_docx: true,
  has_pdf: true,
};

it("keeps the cover letter's warnings beside the document without its details", () => {
  render(<DocumentsCard jobId="j1" coverLetter={letter} readOnly coverDetails={false} />);
  expect(screen.getByText("Cover letter warnings")).toBeTruthy();
  expect(screen.getByText("Dropped a claim the resume does not support.")).toBeTruthy();
  expect(screen.queryByText("Dear team, I build things.")).toBeNull();
});
