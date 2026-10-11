// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CoverLetterSettings } from "../../../api";
import { ToastProvider } from "../../ui";
import { CoverLetterCard } from "./CoverLetterCard";

const api = vi.hoisted(() => ({
  fetchCoverLetterSettings: vi.fn(),
  saveCoverLetterSettings: vi.fn(),
  fetchCoverLetterPreview: vi.fn(),
}));
vi.mock("../../../api", () => api);

const settings: CoverLetterSettings = {
  letterhead: "same_as_resume",
  letterhead_fields: [],
  blocks: {
    date: true,
    recipient: true,
    subject: false,
    salutation: true,
    closing: true,
    signature: true,
  },
  subject_format: "Application for {job_title}",
  closing_text: "Sincerely,",
};
const fields = [
  { id: "email", label: "Email", has_value: true },
  { id: "custom:street_address", label: "Street address", has_value: true },
];

beforeEach(() => {
  api.fetchCoverLetterSettings.mockResolvedValue({ settings, fields });
  api.saveCoverLetterSettings.mockImplementation(async (next: CoverLetterSettings) => ({
    settings: next,
    fields,
  }));
  api.fetchCoverLetterPreview.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("edits a draft with a live preview and saves it", async () => {
  render(
    <ToastProvider>
      <CoverLetterCard reloadKey="r1" />
    </ToastProvider>,
  );
  expect(await screen.findByText("Letterhead matches your resume")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Customize" }));

  const save = screen.getByRole("button", { name: "Save" });
  expect(save.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByText("Subject line"));
  fireEvent.click(screen.getByRole("checkbox", { name: /Street address/ }));
  expect(screen.getByDisplayValue("Application for {job_title}")).toBeTruthy();

  expect(await screen.findByRole("img", { name: "Cover letter preview" })).toBeTruthy();
  const previewed = api.fetchCoverLetterPreview.mock.calls.at(-1)?.[0] as CoverLetterSettings;
  expect(previewed.blocks.subject).toBe(true);
  expect(api.saveCoverLetterSettings).not.toHaveBeenCalled();

  fireEvent.click(save);
  await waitFor(() => expect(api.saveCoverLetterSettings).toHaveBeenCalledTimes(1));
  const saved = api.saveCoverLetterSettings.mock.calls[0][0] as CoverLetterSettings;
  expect(saved.letterhead).toBe("custom");
  expect(saved.letterhead_fields).toEqual(["email"]);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.getByText("Letterhead: Email · with a subject line")).toBeTruthy();
});
