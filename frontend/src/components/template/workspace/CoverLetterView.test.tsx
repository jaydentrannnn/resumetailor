// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CoverLetterSettings } from "../../../api";
import { CoverLetterView } from "./CoverLetterView";

const api = vi.hoisted(() => ({
  fetchCoverLetterSettings: vi.fn(),
  saveCoverLetterSettings: vi.fn(),
  fetchCoverLetterPreview: vi.fn(),
  uploadOwnLetter: vi.fn(),
  removeOwnLetter: vi.fn(),
}));
vi.mock("../../../api", () => ({ ...api, COVER_STARTER_URL: "/api/cover-letter/starter" }));
vi.mock("../../../state/confirmState", () => ({
  useConfirm: () => ({ confirm: vi.fn(async () => true) }),
}));

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
  design: "generated",
};
const fields = [
  { id: "email", label: "Email", has_value: true },
  { id: "custom:street_address", label: "Street address", has_value: true },
];

beforeEach(() => {
  window.localStorage.clear();
  api.fetchCoverLetterSettings.mockResolvedValue({ settings, fields, own_letter: false });
  api.saveCoverLetterSettings.mockImplementation(async (next: CoverLetterSettings) => ({
    settings: next,
    fields,
    own_letter: false,
  }));
  api.fetchCoverLetterPreview.mockResolvedValue(new Blob(["png"], { type: "image/png" }));
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

it("lists the parts in print order and saves a switch as it changes", async () => {
  render(<CoverLetterView reloadKey="r1" />);
  const subject = await screen.findByRole("switch", { name: "Subject line" });
  const names = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
  expect(names[0]).toMatch(/Letterhead/);
  expect(names[5]).toMatch(/^Body/);
  expect(names).toHaveLength(8);
  expect(screen.queryByRole("button", { name: /Quick adjustments/ })).toBeNull();

  fireEvent.click(subject);
  await waitFor(() => expect(api.saveCoverLetterSettings).toHaveBeenCalledTimes(1));
  const saved = api.saveCoverLetterSettings.mock.calls[0][0] as CoverLetterSettings;
  expect(saved.blocks.subject).toBe(true);
  await waitFor(() => {
    const previewed = api.fetchCoverLetterPreview.mock.calls.at(-1)?.[0] as CoverLetterSettings;
    expect(previewed.blocks.subject).toBe(true);
  });
  expect(await screen.findByRole("img", { name: "Cover letter preview" })).toBeTruthy();
});

it("opens only parts with options, and only while they print", async () => {
  render(<CoverLetterView reloadKey="r1" />);
  const letterhead = await screen.findByRole("button", { name: /Letterhead/ });
  expect(letterhead.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("button", { name: /^Date/ })).toBeNull();
  // Subject is off, so its pattern has nothing to open yet.
  expect(screen.queryByRole("button", { name: /Subject line/ })).toBeNull();

  fireEvent.click(letterhead);
  expect(letterhead.getAttribute("aria-expanded")).toBe("true");
  fireEvent.click(screen.getByRole("checkbox", { name: /Street address/ }));
  await waitFor(() => expect(api.saveCoverLetterSettings).toHaveBeenCalled());
  const saved = api.saveCoverLetterSettings.mock.calls.at(-1)?.[0] as CoverLetterSettings;
  expect(saved.letterhead_fields).toEqual(["email"]);
  expect(window.localStorage.getItem("rt.coverParts.open")).toBe('["letterhead"]');
});

it("coalesces typing into one save and reverts when the save fails", async () => {
  render(<CoverLetterView reloadKey="r1" />);
  fireEvent.click(await screen.findByRole("button", { name: /Sign-off/ }));
  vi.useFakeTimers();
  const input = screen.getByRole("textbox", { name: "Sign-off word" });
  api.saveCoverLetterSettings.mockRejectedValueOnce(new Error("busy"));
  fireEvent.change(input, { target: { value: "Best" } });
  fireEvent.change(input, { target: { value: "Best," } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(600);
  });
  vi.useRealTimers();
  expect(api.saveCoverLetterSettings).toHaveBeenCalledTimes(1);
  expect(await screen.findByText(/Couldn't save/)).toBeTruthy();
  expect((screen.getByRole("textbox", { name: "Sign-off word" }) as HTMLInputElement).value).toBe(
    "Sincerely,",
  );
});

it("choosing your own letter waits for an upload before saving", async () => {
  render(<CoverLetterView reloadKey="r1" />);
  fireEvent.click(await screen.findByRole("radio", { name: "Your own letter" }));
  expect(screen.getByRole("link", { name: "Download starter letter" })).toBeTruthy();
  // An own letter's letterhead is its file, so that part leaves the list.
  expect(screen.queryByRole("button", { name: /Letterhead/ })).toBeNull();
  await new Promise((r) => setTimeout(r, 700));
  expect(api.saveCoverLetterSettings).not.toHaveBeenCalled();
});
