// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchConfig, fetchMasterResume, saveMasterResume } from "../../api";
import { type MasterResume, stripRowKeys, withRowKeys } from "../../lib/resumeEdit";
import { moveEntryToSection, resumeEntryKey } from "../../lib/resumeEntryEdit";
import { EditorProvider } from "../../state/editorState";
import { ConfirmProvider } from "../../state/confirmState";
import { EditorPage } from "./EditorPage";

vi.mock("../../api", () => ({
  fetchConfig: vi.fn(),
  fetchMasterResume: vi.fn(),
  saveMasterResume: vi.fn(),
  validateMasterResume: vi.fn(),
  suggestTags: vi.fn(),
  suggestTagsAI: vi.fn(),
}));
vi.mock("../../components/ImportResumePanel", () => ({ ImportResumePanel: () => null }));
vi.mock("../../components/ResumeHistoryList", () => ({ ResumeHistoryList: () => null }));

function fixture(): MasterResume {
  return {
    contact: { name: "Test User", email: "test@example.com" },
    sections: [
      {
        id: "education",
        title: "Education",
        kind: "education",
        entries: [
          {
            school: "State University",
            degree: "BS Computer Science",
            dates: "2020–2024",
            coursework: ["Databases"],
          },
          { school: "Other University", degree: "MS", dates: "2024–2026" },
        ],
      },
      {
        id: "experience",
        title: "Experience",
        kind: "experience",
        entries: [
          {
            id: "acme",
            company: "Acme",
            title: "Engineer",
            start: "2024-01",
            end: "Present",
            bullets: [
              { id: "acme_b1", text: "Built Python tools", tags: ["python"], metric: false },
            ],
          },
        ],
      },
      { id: "research", title: "Research", kind: "experience", entries: [] },
      {
        id: "projects",
        title: "Projects",
        kind: "project",
        entries: [{ id: "search", name: "Search Tool", tech: ["Python"], bullets: [] }],
      },
      {
        id: "skills",
        title: "Skills",
        kind: "skills",
        entries: [{ label: "Languages", items: ["Python"] }],
      },
      {
        id: "certs",
        title: "Certifications",
        kind: "list",
        entries: [{ id: "item_1", text: "Cloud Certificate" }],
      },
      // List ids are section-local: moving this row must not alias the other row's UI state.
      {
        id: "awards",
        title: "Awards",
        kind: "list",
        entries: [{ id: "item_1", text: "Academic Award" }],
      },
    ],
    tag_vocabulary: ["python"],
  };
}

let persisted: MasterResume;
beforeEach(() => {
  vi.clearAllMocks();
  persisted = fixture();
  vi.mocked(fetchMasterResume).mockImplementation(
    async () => persisted as unknown as Record<string, unknown>,
  );
  vi.mocked(fetchConfig).mockResolvedValue({ tag_vocabulary: ["python"] } as Awaited<
    ReturnType<typeof fetchConfig>
  >);
  vi.mocked(saveMasterResume).mockImplementation(async (payload) => {
    persisted = payload as unknown as MasterResume;
    return { ok: true, errors: [], summary: { name: "Test User", bullets: 1, tags: 1 } };
  });
});
afterEach(cleanup);

async function editor() {
  const view = render(
    <ConfirmProvider>
      <EditorProvider>
        <EditorPage showContact={false} />
      </EditorProvider>
    </ConfirmProvider>,
  );
  await screen.findByRole("button", { name: "Expand State University" });
  return view;
}

function section(id: string) {
  return within(document.getElementById(`resume-section-${id}`)!);
}

it("collapses every entry kind and keeps edits and chip drafts across collapse/reorder", async () => {
  await editor();
  for (const title of [
    "State University",
    "Acme · Engineer",
    "Search Tool",
    "Languages",
    "Cloud Certificate",
  ]) {
    expect(screen.getByRole("button", { name: `Expand ${title}` })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  }
  expect(screen.queryByRole("textbox", { name: "Company" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Expand State University" }));
  const school = section("education").getAllByLabelText("School")[0];
  fireEvent.change(school, { target: { value: "Updated University" } });
  const coursework = section("education").getAllByLabelText("Relevant coursework")[0];
  fireEvent.change(coursework, { target: { value: "Algorithms" } });
  fireEvent.click(screen.getByRole("button", { name: "Collapse Updated University" }));
  expect(school).not.toBeVisible();
  expect(screen.queryByText("Unsaved changes")).toBeInTheDocument();
  const card = screen
    .getByRole("button", { name: "Expand Updated University" })
    .closest("[data-resume-entry]")!;
  fireEvent.click(within(card as HTMLElement).getByRole("button", { name: "Move down" }));
  fireEvent.click(screen.getByRole("button", { name: "Expand Updated University" }));
  expect(school).toBeVisible();
  expect(school).toHaveValue("Updated University");
  expect(coursework).toHaveValue("Algorithms");
  expect(screen.getByRole("button", { name: "Expand Other University" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("opens new entries for all five kinds without opening existing entries", async () => {
  await editor();
  for (const [id, addLabel, field] of [
    ["education", "Add entry", "School"],
    ["experience", "Add entry", "Company"],
    ["projects", "Add entry", "Name"],
    ["skills", "Add group", "Label"],
    ["certs", "Add line", "Line text"],
  ]) {
    fireEvent.click(section(id).getByRole("button", { name: addLabel }));
    const inputs = section(id).getAllByRole("textbox", { name: field, exact: true });
    expect(inputs).toHaveLength(1);
    expect(inputs[0]).toBeVisible();
    expect(inputs[0]).toHaveValue("");
  }
  expect(screen.getByRole("button", { name: "Expand State University" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("offers only matching destinations, preserves expansion and content, undoes, and saves", async () => {
  await editor();
  fireEvent.click(screen.getByRole("button", { name: "Expand Acme · Engineer" }));
  expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  const select = screen.getByRole("combobox", { name: "Move Acme · Engineer to section" });
  expect(
    within(select)
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["Move to…", "Research"]);
  expect(
    screen.queryByRole("combobox", { name: "Move Search Tool to section" }),
  ).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: "research" } });
  expect(section("experience").queryByRole("button", { name: /Acme/ })).not.toBeInTheDocument();
  expect(section("research").getByRole("textbox", { name: "Company" })).toHaveValue("Acme");
  expect(screen.getByRole("button", { name: "Collapse Acme · Engineer" })).toBeVisible();
  expect(saveMasterResume).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(section("experience").getByRole("textbox", { name: "Company" })).toBeVisible();
  expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Move Acme · Engineer to section" }), {
    target: { value: "research" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
  await waitFor(() => expect(saveMasterResume).toHaveBeenCalledTimes(1));
  const payload = vi.mocked(saveMasterResume).mock.calls[0][0] as unknown as MasterResume;
  expect(payload.sections.find((s) => s.id === "experience")?.entries).toEqual([]);
  expect(payload.sections.find((s) => s.id === "research")?.entries).toEqual(
    fixture().sections[1].entries,
  );
  expect(payload).toEqual(stripRowKeys(payload));
  await waitFor(() => expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument());
});

it("keeps list rows independent when their ids collide in the destination", async () => {
  await editor();
  fireEvent.click(screen.getByRole("button", { name: "Expand Cloud Certificate" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Move Cloud Certificate to section" }), {
    target: { value: "awards" },
  });
  expect(section("awards").getByRole("textbox", { name: "Line text" })).toHaveValue(
    "Cloud Certificate",
  );
  expect(screen.getByRole("button", { name: "Expand Academic Award" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  fireEvent.click(screen.getByRole("button", { name: "Expand Academic Award" }));
  expect(section("awards").getAllByRole("textbox", { name: "Line text" })).toHaveLength(2);
});

describe("moveEntryToSection", () => {
  it.each(["experience", "project", "education", "skills", "list"] as const)(
    "transfers %s entries unchanged and appends after existing entries",
    (kind) => {
      const original = withRowKeys(fixture());
      const source = original.sections.find((s) => s.kind === kind)!;
      const entry = source.entries[0];
      const destination = { ...source, id: "destination", entries: [...source.entries] };
      const resume = { ...original, sections: [...original.sections, destination] } as MasterResume;
      const result = moveEntryToSection(resume, source.id, resumeEntryKey(entry), destination.id);
      expect(result.sections.find((s) => s.id === source.id)?.entries).toEqual(
        source.entries.slice(1),
      );
      expect(result.sections.at(-1)?.entries.at(-1)).toBe(entry);
      expect(result.sections.at(-1)?.entries).toHaveLength(source.entries.length + 1);
      expect(source.entries[0]).toBe(entry);
    },
  );

  it("rejects incompatible, same-section and stale moves without changing the draft", () => {
    const resume = withRowKeys(fixture());
    for (const [source, key, destination] of [
      ["experience", "acme", "projects"],
      ["experience", "acme", "experience"],
      ["missing", "acme", "research"],
      ["experience", "acme", "missing"],
      ["experience", "missing", "research"],
    ])
      expect(moveEntryToSection(resume, source, key, destination)).toBe(resume);
  });
});
