// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { resetDesktopForTests } from "../lib/useDesktop";
import { JobFileActions, OpenDocumentLink, SaveFileButton } from "./FileActions";

const api = vi.hoisted(() => ({
  fetchConfig: vi.fn(),
  saveFileAs: vi.fn(),
  revealJobFile: vi.fn(),
  openJobFile: vi.fn(),
}));
vi.mock("../api", () => api);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetDesktopForTests();
});

function host(desktop: boolean) {
  api.fetchConfig.mockResolvedValue({ desktop });
}

it("browser build: plain download links, no folder or Word actions", async () => {
  host(false);
  render(
    <>
      <SaveFileButton url="/api/jobs/j1/download.pdf" what="PDF" fallbackName="resume.pdf" />
      <JobFileActions jobId="j1" kind="resume-docx" />
      <OpenDocumentLink href="/api/jobs/j1/preview.pdf" />
    </>,
  );
  await waitFor(() => expect(api.fetchConfig).toHaveBeenCalled());
  const link = screen.getByRole("link", { name: "Download PDF" });
  expect(link.getAttribute("href")).toBe("/api/jobs/j1/download.pdf");
  expect(link.hasAttribute("download")).toBe(true);
  expect(screen.getByRole("link", { name: "Open in new tab" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Show in folder" })).toBeNull();
});

it("desktop app: Save as… goes through the server, with folder and Word actions", async () => {
  host(true);
  api.saveFileAs.mockResolvedValue({ saved: false, path: null });
  api.revealJobFile.mockResolvedValue(undefined);
  api.openJobFile.mockResolvedValue(undefined);
  render(
    <>
      <SaveFileButton url="/api/jobs/j1/download.pdf" what="PDF" fallbackName="resume.pdf" />
      <JobFileActions jobId="j1" kind="resume-docx" />
      <OpenDocumentLink href="/api/jobs/j1/preview.pdf" />
    </>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Save PDF…" }));
  expect(api.saveFileAs).toHaveBeenCalledWith("/api/jobs/j1/download.pdf", "resume.pdf");
  fireEvent.click(screen.getByRole("button", { name: "Show in folder" }));
  fireEvent.click(screen.getByRole("button", { name: "Open in Word" }));
  expect(api.revealJobFile).toHaveBeenCalledWith("j1", "resume-docx");
  expect(api.openJobFile).toHaveBeenCalledWith("j1", "resume-docx");
  expect(screen.getByRole("link", { name: "Open in window" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Download PDF" })).toBeNull();
});

it("desktop app: a file the server writes itself never goes through the page", async () => {
  host(true);
  const desktopSave = vi.fn().mockResolvedValue({ saved: true, path: "C:/b.zip" });
  render(
    <SaveFileButton
      url="/api/data/export.zip"
      what="profile export"
      fallbackName="p.zip"
      desktopSave={desktopSave}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Save profile export…" }));
  await waitFor(() => expect(desktopSave).toHaveBeenCalledTimes(1));
  expect(api.saveFileAs).not.toHaveBeenCalled();
});
