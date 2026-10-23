// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidenceProposal, EvidenceView } from "../../api";
import { EvidencePage } from "./EvidencePage";

const api = vi.hoisted(() => ({
  getEvidence: vi.fn(),
  addEvidenceToResume: vi.fn(),
  keepEvidenceForMatching: vi.fn(),
  dismissEvidence: vi.fn(),
  reopenEvidence: vi.fn(),
  scanEvidenceSource: vi.fn(),
  removeEvidenceSource: vi.fn(),
  addGitHubEvidence: vi.fn(),
  addTextEvidence: vi.fn(),
  addFileEvidence: vi.fn(),
}));
vi.mock("../../api", () => api);

const editor = vi.hoisted(() => ({ dirty: false, syncFromDisk: vi.fn(), resume: null as unknown }));
vi.mock("../../state/editorState", () => ({ useEditorState: () => editor }));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  editor.dirty = false;
});

const resume = {
  contact: { name: "J" },
  sections: [
    {
      id: "x",
      kind: "experience",
      title: "Experience",
      entries: [{ id: "acme", company: "Acme", title: "Intern", bullets: [] }],
    },
    { id: "s", kind: "skills", title: "Skills", entries: [{ label: "Tools", items: [] }] },
  ],
};

const proposal = (over: Partial<EvidenceProposal>): EvidenceProposal => ({
  id: "e1",
  source_id: "s1",
  kind: "bullet",
  target_entry_id: "acme",
  new_project: null,
  text: "Built a flashcard CLI",
  excerpt: "Built a command-line tool.",
  basis: "stated",
  question: "",
  state: "pending",
  decided_at: "",
  added_to: "",
  ...over,
});

const view = (proposals: EvidenceProposal[]): EvidenceView => ({
  sources: [
    {
      id: "s1",
      kind: "github",
      title: "jordan/cards",
      url: "https://github.com/jordan/cards",
      added_at: "",
      flags: [],
      attribution: "own",
      commit_share: 1,
      languages: ["Rust"],
      scanned_at: "2026-10-23T10:00:00+00:00",
      dropped: 0,
      drop_reasons: {},
      model: "",
      chars: 90,
    },
  ],
  proposals,
  matching: {},
  github_user: "jordan",
  github_token: false,
  warnings: [],
});

const renderPage = () =>
  render(
    <MemoryRouter>
      <EvidencePage />
    </MemoryRouter>,
  );

describe("EvidencePage", () => {
  it("shows each item with its quote and offers Matching only for skills alone", async () => {
    editor.resume = resume;
    api.getEvidence.mockResolvedValue(
      view([
        proposal({}),
        proposal({
          id: "e2",
          kind: "skill",
          text: "Rust",
          basis: "inferred",
          question: "Did you write the Rust yourself?",
        }),
      ]),
    );
    renderPage();

    expect(await screen.findByText("Built a flashcard CLI")).toBeTruthy();
    expect(screen.getAllByText("“Built a command-line tool.”")).toHaveLength(2);
    expect(screen.getByText("Did you write the Rust yourself?")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Matching only" })).toHaveLength(1);
    expect(screen.getByText("Your repository · 100% of commits")).toBeTruthy();
  });

  it("adds an item as edited and hands the saved resume to the editor", async () => {
    editor.resume = resume;
    api.getEvidence.mockResolvedValue(view([proposal({})]));
    api.addEvidenceToResume.mockResolvedValue({
      evidence: view([proposal({ state: "added" })]),
      resume,
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Add to resume…" }));
    fireEvent.change(screen.getByLabelText("Bullet"), { target: { value: "Built a Rust CLI" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Rust" }));
    fireEvent.click(screen.getByRole("button", { name: "Add to resume" }));

    await waitFor(() =>
      expect(api.addEvidenceToResume).toHaveBeenCalledWith("e1", {
        text: "Built a Rust CLI",
        target_entry_id: "acme",
        skills: ["Rust"],
      }),
    );
    await waitFor(() =>
      expect(editor.syncFromDisk).toHaveBeenCalledWith(resume, "Added from evidence."),
    );
  });

  it("holds Add while the resume has unsaved edits", async () => {
    editor.dirty = true;
    api.getEvidence.mockResolvedValue(view([proposal({})]));
    renderPage();
    const add = await screen.findByRole("button", { name: "Add to resume…" });
    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Save or discard your resume edits first.")).toBeTruthy();
  });
});
