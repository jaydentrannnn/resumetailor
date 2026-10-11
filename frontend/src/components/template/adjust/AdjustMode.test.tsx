// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AdjustMode } from "./AdjustMode";

const api = vi.hoisted(() => ({
  fetchTemplateAdjustments: vi.fn(),
  fetchTemplateFonts: vi.fn(),
  fetchAdjustPreview: vi.fn(),
  adjustPreviewPageUrl: (key: string, page: number) => `/preview/${key}/${page}.png`,
  adjustTemplate: vi.fn(),
  fetchEditedLayout: vi.fn(),
  uploadTemplate: vi.fn(),
}));
vi.mock("../../../api", () => api);
const template = vi.hoisted(() => ({
  info: { active_label: "Nina" },
  beginFromAnalysis: vi.fn(),
  refreshLibrary: vi.fn(async () => undefined),
}));
vi.mock("../../../state/templateState", () => ({ useTemplateState: () => template }));
const confirm = vi.hoisted(() => vi.fn(async () => true));
vi.mock("../../../state/confirmState", () => ({ useConfirm: () => ({ confirm }) }));

const CURRENT = {
  margins: { top: 1, bottom: 1, left: 1, right: 1 },
  font_family: "Calibri",
  font_size: 11,
  fields: [{ label: "Company", bold: true, italic: false, underline: false }],
  separators: { contact: " | ", tech_items: ", " },
  bullets: { list: "keep", skills: "keep" },
  links: null,
};

beforeEach(() => {
  api.fetchTemplateAdjustments.mockResolvedValue({ current: CURRENT, table_layout: false });
  api.fetchTemplateFonts.mockResolvedValue({
    families: ["Calibri", "Georgia"],
    common: ["Calibri"],
  });
  api.fetchAdjustPreview.mockResolvedValue({ key: "k1", pages: 2 });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows only the rows the template has", async () => {
  render(<AdjustMode onDone={() => undefined} />);
  expect(await screen.findByLabelText("Contact info")).toBeTruthy();
  expect(screen.getByLabelText("Between tools")).toBeTruthy();
  expect(screen.queryByLabelText("Between skills")).toBeNull();
  // No links in this template, so no Links section.
  expect(screen.queryByText("Links")).toBeNull();
});

it("renders the draft preview pages", async () => {
  render(<AdjustMode onDone={() => undefined} />);
  expect(await screen.findByAltText("Draft page 2", undefined, { timeout: 2000 })).toBeTruthy();
  expect(screen.getByText(/2 pages/)).toBeTruthy();
});

it("asks before discarding a changed draft", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  fireEvent.change(await screen.findByLabelText("Left"), { target: { value: "0.5" } });
  confirm.mockResolvedValueOnce(false);
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(confirm).toHaveBeenCalled());
  expect(onDone).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
});

it("leaves an unchanged draft without asking", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  await screen.findByLabelText("Left");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(confirm).not.toHaveBeenCalled();
});

it("installs the adjusted layout on Apply", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  const apply = await screen.findByRole("button", { name: "Apply" });
  expect(apply.hasAttribute("disabled")).toBe(true);

  fireEvent.change(screen.getByLabelText("Lists"), { target: { value: "–" } });
  fireEvent.click(screen.getByRole("button", { name: "Italic Company" }));
  const analysis = { source_sha256: "b".repeat(64), ready: true, suggested_profile: { p: 1 } };
  const file = new File(["x"], "layout.docx");
  api.adjustTemplate.mockResolvedValue(analysis);
  api.fetchEditedLayout.mockResolvedValue(file);
  api.uploadTemplate.mockResolvedValue({});
  fireEvent.click(apply);

  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(api.adjustTemplate).toHaveBeenCalledWith({
    bullets: { list: "–", skills: "keep" },
    fields: [{ label: "Company", italic: true }],
  });
  expect(api.uploadTemplate).toHaveBeenCalledWith(
    file,
    { p: 1 },
    {
      calibrate: true,
      label: "Nina (adjusted)",
    },
  );
  expect(template.refreshLibrary).toHaveBeenCalled();
  expect(template.beginFromAnalysis).not.toHaveBeenCalled();
});

it("hands a read-back that needs review to the importer", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  fireEvent.change(await screen.findByLabelText("Left"), { target: { value: "0.5" } });
  const analysis = { source_sha256: "c".repeat(64), ready: false, suggested_profile: null };
  const file = new File(["x"], "layout.docx");
  api.adjustTemplate.mockResolvedValue(analysis);
  api.fetchEditedLayout.mockResolvedValue(file);
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));

  await waitFor(() =>
    expect(template.beginFromAnalysis).toHaveBeenCalledWith(file, analysis, "Nina (adjusted)"),
  );
  expect(api.uploadTemplate).not.toHaveBeenCalled();
  expect(onDone).toHaveBeenCalled();
});
