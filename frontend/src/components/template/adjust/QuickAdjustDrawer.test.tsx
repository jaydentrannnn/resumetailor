// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QuickAdjustDrawer } from "./QuickAdjustDrawer";

const api = vi.hoisted(() => ({
  fetchTemplateAdjustments: vi.fn(),
  adjustTemplate: vi.fn(),
  fetchEditedLayout: vi.fn(),
}));
vi.mock("../../../api", () => api);
const template = vi.hoisted(() => ({
  info: { active_label: "Nina" },
  beginFromAnalysis: vi.fn(),
}));
vi.mock("../../../state/templateState", () => ({ useTemplateState: () => template }));

beforeEach(() => {
  api.fetchTemplateAdjustments.mockResolvedValue({
    current: {
      margins: { top: 1, bottom: 1, left: 1, right: 1 },
      font_family: "Calibri",
      font_size: 11,
      fields: [{ label: "Company", bold: true, italic: false, underline: false }],
    },
    table_layout: false,
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("sends only the changes and opens the result in the wizard", async () => {
  const onClose = vi.fn();
  render(<QuickAdjustDrawer onClose={onClose} />);
  const review = await screen.findByRole("button", { name: "Review changes" });
  expect(review.hasAttribute("disabled")).toBe(true);

  fireEvent.click(screen.getByRole("button", { name: "Italic Company" }));
  fireEvent.change(screen.getByLabelText("Left"), { target: { value: "0.5" } });
  const analysis = { source_sha256: "b".repeat(64) };
  const file = new File(["x"], "layout.docx");
  api.adjustTemplate.mockResolvedValue(analysis);
  api.fetchEditedLayout.mockResolvedValue(file);
  fireEvent.click(review);

  await waitFor(() =>
    expect(template.beginFromAnalysis).toHaveBeenCalledWith(file, analysis, "Nina (adjusted)"),
  );
  expect(api.adjustTemplate).toHaveBeenCalledWith({
    margins: { top: 1, bottom: 1, left: 0.5, right: 1 },
    fields: [{ label: "Company", italic: true }],
  });
  expect(onClose).toHaveBeenCalled();
});

it("shows the table-width note for a table layout", async () => {
  api.fetchTemplateAdjustments.mockResolvedValueOnce({
    ...(await api.fetchTemplateAdjustments()),
    table_layout: true,
  });
  render(<QuickAdjustDrawer onClose={() => undefined} />);
  expect(await screen.findByText(/keeps its width/)).toBeTruthy();
});
