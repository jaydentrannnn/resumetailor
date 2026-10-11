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
  library: [] as { label: string; is_active: boolean }[],
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
  fields: [
    { label: "Company", bold: true, italic: false, underline: false },
    { label: "GitHub", bold: false, italic: false, underline: false },
  ],
  separators: { contact: " | ", tech_items: ", " },
  bullets: { list: "keep", skills: "keep" },
  links: null as null | { color: string; underline: boolean },
};

const section = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

beforeEach(() => {
  template.library = [];
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

it("starts with the groups collapsed and opens one at a time", async () => {
  render(<AdjustMode onDone={() => undefined} />);
  const margins = await screen.findByRole("button", { name: /Margins/ });
  expect(margins.getAttribute("aria-expanded")).toBe("false");
  expect(screen.getByText('1" all sides')).toBeTruthy();
  expect(screen.queryByLabelText("Left")).toBeNull();

  section("Margins");
  expect(screen.getByLabelText("Left")).toBeTruthy();
  section("Separators");
  expect(screen.queryByLabelText("Left")).toBeNull();
  expect(screen.getByLabelText("Contact info")).toBeTruthy();
  expect(screen.getByLabelText("Between tools")).toBeTruthy();
  expect(screen.queryByLabelText("Between skills")).toBeNull();
});

it("shows the links row only when the template prints links, and drops link fields' U", async () => {
  render(<AdjustMode onDone={() => undefined} />);
  fireEvent.click(await screen.findByRole("button", { name: "Field emphasis" }));
  expect(screen.queryByRole("button", { name: "Blue links" })).toBeNull();
  expect(screen.getByRole("button", { name: "Underline GitHub" })).toBeTruthy();
  cleanup();

  api.fetchTemplateAdjustments.mockResolvedValue({
    current: { ...CURRENT, links: { color: "blue", underline: true } },
    table_layout: false,
  });
  render(<AdjustMode onDone={() => undefined} />);
  fireEvent.click(await screen.findByRole("button", { name: /Field emphasis/ }));
  expect(screen.queryByRole("button", { name: "Underline GitHub" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Blue links" }));
  expect(screen.getByRole("button", { description: "1 changed" })).toBeTruthy();
});

it("renders the draft preview pages", async () => {
  render(<AdjustMode onDone={() => undefined} />);
  expect(await screen.findByAltText("Draft page 2", undefined, { timeout: 2000 })).toBeTruthy();
  expect(screen.getByText(/2 pages/)).toBeTruthy();
});

it("asks before discarding a changed draft", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  fireEvent.click(await screen.findByRole("button", { name: /Margins/ }));
  fireEvent.change(screen.getByLabelText("Left"), { target: { value: "0.5" } });
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
  await screen.findByRole("button", { name: /Margins/ });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(confirm).not.toHaveBeenCalled();
});

it("installs the adjusted layout on Apply, replacing one of the same name", async () => {
  template.library = [{ label: "Nina (adjusted)", is_active: false }];
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  const apply = await screen.findByRole("button", { name: "Apply" });
  expect(apply.hasAttribute("disabled")).toBe(true);
  expect(screen.getByText(/replaces your earlier “Nina \(adjusted\)”; Nina stays/)).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: /Bullet styles/ }));
  fireEvent.change(screen.getByLabelText("Lists"), { target: { value: "–" } });
  fireEvent.click(screen.getByRole("button", { name: /Field emphasis/ }));
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
    { calibrate: true, label: "Nina (adjusted)", replace: true },
  );
  expect(template.refreshLibrary).toHaveBeenCalled();
  expect(template.beginFromAnalysis).not.toHaveBeenCalled();
});

it("hands a read-back that needs review to the importer", async () => {
  const onDone = vi.fn();
  render(<AdjustMode onDone={onDone} />);
  fireEvent.click(await screen.findByRole("button", { name: /Margins/ }));
  fireEvent.change(screen.getByLabelText("Left"), { target: { value: "0.5" } });
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
