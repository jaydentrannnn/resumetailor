// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { CoverLetterSettings } from "../../../api";
import { LetterDesignSection } from "./LetterDesignSection";

vi.mock("../../../api", () => ({ COVER_STARTER_URL: "/api/cover-letter/starter" }));
const confirm = vi.hoisted(() => vi.fn());
vi.mock("../../../state/confirmState", () => ({ useConfirm: () => ({ confirm }) }));

const base: CoverLetterSettings = {
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
  design: "own",
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function upload(file: File) {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

it("lists a rejected letter's problems and keeps the design unchanged", async () => {
  const onChange = vi.fn();
  const onUpload = vi.fn(async () => ["Add «Body» on its own line."]);
  render(
    <LetterDesignSection
      settings={base}
      ownLetter={false}
      onChange={onChange}
      onUpload={onUpload}
      onRemove={vi.fn()}
    />,
  );
  expect(screen.getByRole("link", { name: "Download starter letter" })).toBeTruthy();
  upload(new File(["x"], "mine.docx"));
  expect(await screen.findByText("Add «Body» on its own line.")).toBeTruthy();
  expect(onChange).not.toHaveBeenCalled();
});

it("an accepted letter selects it; removing asks first", async () => {
  const onChange = vi.fn();
  const onRemove = vi.fn(async () => undefined);
  render(
    <LetterDesignSection
      settings={base}
      ownLetter
      onChange={onChange}
      onUpload={vi.fn(async () => [])}
      onRemove={onRemove}
    />,
  );
  upload(new File(["x"], "mine.docx"));
  await waitFor(() => expect(onChange).toHaveBeenCalledWith({ ...base, design: "own" }));

  confirm.mockResolvedValueOnce(true);
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(onRemove).toHaveBeenCalled());
  expect(onChange).toHaveBeenLastCalledWith({ ...base, design: "generated" });
});
