// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mergeMasterResume, previewMasterResumeMerge } from "../../api";
import { useTemplateContentImport } from "./useTemplateContentImport";

const EMPTY = { contact: { name: "" }, sections: [{ kind: "experience", entries: [] }] };
const editor = { resume: EMPTY, dirty: false, loadDraft: vi.fn(), syncFromDisk: vi.fn() };
const choice = vi.fn(async () => "merge");

vi.mock("../../api", () => ({
  importMasterResumeContent: vi.fn(async () => ({ resume: EMPTY, warnings: [] })),
  previewMasterResumeMerge: vi.fn(),
  mergeMasterResume: vi.fn(async () => ({
    resume: EMPTY,
    updated: [],
    added: [],
    added_sections: [],
    warnings: [],
    backup: null,
  })),
}));
vi.mock("../../state/editorState", () => ({ useEditorState: () => editor }));
vi.mock("../../state/confirmState", () => ({ useConfirm: () => ({ choice }) }));

const plan = (existingEmpty: boolean) => ({
  pairs: [],
  options: [],
  revision: "rev1",
  existing_empty: existingEmpty,
});

async function runImport() {
  const { result } = renderHook(() => useTemplateContentImport());
  await act(async () => {
    await result.current.importContent(new File(["x"], "resume.docx"));
  });
}

describe("importing a resume's words", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    editor.resume = EMPTY;
    editor.dirty = false;
  });

  it("asks first when the saved resume has entries, even if the editor looks empty", async () => {
    vi.mocked(previewMasterResumeMerge).mockResolvedValue(plan(false));
    await runImport();
    expect(choice).toHaveBeenCalledOnce();
    expect(mergeMasterResume).toHaveBeenCalledWith(EMPTY, {}, "rev1");
  });

  it("asks first, and says so, when the Resume page has unsaved edits", async () => {
    editor.dirty = true;
    vi.mocked(previewMasterResumeMerge).mockResolvedValue(plan(true));
    await runImport();
    expect(choice).toHaveBeenCalledOnce();
    expect(choice.mock.calls[0][0]).toMatchObject({
      message: expect.stringContaining("unsaved changes"),
    });
  });

  it("saves straight away into an empty saved resume with nothing unsaved", async () => {
    vi.mocked(previewMasterResumeMerge).mockResolvedValue(plan(true));
    await runImport();
    expect(choice).not.toHaveBeenCalled();
    expect(mergeMasterResume).toHaveBeenCalledWith(EMPTY, {}, "rev1");
  });

  it("falls back to the editor's saved copy when the preview fails", async () => {
    vi.mocked(previewMasterResumeMerge).mockRejectedValue(new Error("offline"));
    await runImport();
    expect(choice).not.toHaveBeenCalled();
    expect(mergeMasterResume).toHaveBeenCalledWith(EMPTY, {}, "");
  });
});
