// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchConfig, fetchMasterResume, saveMasterResume } from "../../api";
import { type MasterResume, stripRowKeys, withRowKeys } from "../../lib/resumeEdit";
import { moveEntryToSection, resumeEntryKey } from "../../lib/resumeEntryEdit";
import { EditorProvider } from "../../state/editorState";
import { ConfirmProvider } from "../../state/confirmState";
import { StatusMessage } from "../../components/shell/StatusBar";
import { ToastProvider } from "../../components/ui/Toast";
import { EditorPage } from "./EditorPage";

vi.mock("../../api", () => ({
  fetchConfig: vi.fn(),
  fetchMasterResume: vi.fn(),
  saveMasterResume: vi.fn(),
  validateMasterResume: vi.fn(),
  fetchProfileOptions: vi.fn(async () => ({ degree_types: ["B.A."], fields_of_study: [] })),
  fetchBulletSkills: vi.fn(async () => ({
    running: false,
    error: null,
    waiting: 0,
    bullets: { acme_b1: ["tooling"] },
  })),
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
    <ToastProvider>
      <ConfirmProvider>
        <EditorProvider>
          <EditorPage showContact={false} />
        </EditorProvider>
      </ConfirmProvider>
      <StatusMessage />
    </ToastProvider>,
  );
  await screen.findByRole("button", { name: "Expand State University" });
  return view;
}

function section(id: string) {
  return within(document.getElementById(`resume-section-${id}`)!);
}

it("collapses every entry kind and keeps edits and chip drafts across date reordering", async () => {
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
  const school = section("education").getByRole("textbox", { name: "School", exact: true });
  fireEvent.change(school, { target: { value: "Updated University" } });
  const coursework = section("education").getByRole("textbox", {
    name: "Relevant coursework",
    exact: true,
  });
  fireEvent.change(coursework, { target: { value: "Algorithms" } });
  fireEvent.click(screen.getByRole("button", { name: "Collapse Updated University" }));
  expect(school).not.toBeVisible();
  expect(screen.queryByText("Unsaved changes")).toBeInTheDocument();
  const card = screen
    .getByRole("button", { name: "Expand Updated University" })
    .closest("[data-resume-entry]")!;
  expect(
    within(card as HTMLElement).queryByRole("button", { name: "Move down" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Expand Updated University" }));
  const dates = within(card as HTMLElement).getByRole("textbox", { name: "Dates", exact: true });
  fireEvent.focus(dates);
  fireEvent.change(dates, { target: { value: "2028–2030" } });
  expect(
    section("education").getAllByRole("button", { name: /^(Expand|Collapse)/ })[0],
  ).toHaveTextContent("Other University");
  fireEvent.blur(dates);
  expect(
    section("education").getAllByRole("button", { name: /^(Expand|Collapse)/ })[0],
  ).toHaveTextContent("Updated University");
  expect(school).toBeVisible();
  expect(school).toHaveValue("Updated University");
  expect(coursework).toHaveValue("Algorithms");
  expect(screen.getByRole("button", { name: "Expand Other University" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});

it("drags only between matching sections, preserves edits and expansion, and undoes", async () => {
  await editor();
  fireEvent.click(screen.getByRole("button", { name: "Expand Acme · Engineer" }));
  fireEvent.change(section("experience").getByRole("textbox", { name: "Company" }), {
    target: { value: "Revised" },
  });
  const dataTransfer = {
    setData: vi.fn(),
    setDragImage: vi.fn(),
    effectAllowed: "",
    dropEffect: "",
  };
  const handle = screen.getByRole("button", { name: "Drag Revised · Engineer to another section" });
  fireEvent.dragStart(handle, { dataTransfer });
  fireEvent.drop(document.querySelector('[data-entry-drop-target="projects"]')!, { dataTransfer });
  expect(section("experience").getByRole("textbox", { name: "Company" })).toHaveValue("Revised");
  fireEvent.dragStart(handle, { dataTransfer });
  fireEvent.dragOver(document.querySelector('[data-entry-drop-target="research"]')!, {
    dataTransfer,
  });
  fireEvent.drop(document.querySelector('[data-entry-drop-target="research"]')!, { dataTransfer });
  expect(section("research").getByRole("textbox", { name: "Company" })).toHaveValue("Revised");
  expect(section("experience").queryByRole("button", { name: /Revised/ })).not.toBeInTheDocument();
  expect(saveMasterResume).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Undo" }));
  expect(section("experience").getByRole("textbox", { name: "Company" })).toHaveValue("Revised");
});

it("loads chronological order without a dirty draft and saves a date edit committed on blur", async () => {
  await editor();
  expect(section("education").getAllByRole("button", { name: /^Expand/ })[0]).toHaveTextContent(
    "Other University",
  );
  expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Expand Acme · Engineer" }));
  const endYear = section("experience").getByRole("textbox", { name: "End, year" });
  // Leave the Present checkbox to pick an explicit end date.
  const present = section("experience").getByRole("checkbox", { name: "Present" });
  fireEvent.focus(present);
  fireEvent.click(present);
  fireEvent.change(section("experience").getByRole("combobox", { name: "End, month" }), {
    target: { value: "6" },
  });
  fireEvent.change(endYear, { target: { value: "2025" } });
  expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
  fireEvent.blur(endYear);
  fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
  await waitFor(() => expect(saveMasterResume).toHaveBeenCalledTimes(1));
  const payload = vi.mocked(saveMasterResume).mock.calls[0][0] as unknown as MasterResume;
  const job = payload.sections.find((s) => s.kind === "experience")!.entries[0];
  expect(job).toMatchObject({ end: "2025-06" });
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
  it("inserts a moved dated entry in chronological order in the destination", () => {
    const resume = withRowKeys(fixture());
    const target = resume.sections.find((s) => s.id === "research")!;
    if (target.kind !== "experience") throw new Error("Expected experience section");
    target.entries = [
      {
        id: "prior",
        company: "Prior",
        title: "Engineer",
        start: "2020-01",
        end: "2023-06",
        bullets: [],
      },
      { id: "undated", company: "Unknown", title: "Engineer", start: "", end: "", bullets: [] },
    ];
    const result = moveEntryToSection(resume, "experience", "acme", "research");
    expect(result.sections.find((s) => s.id === "experience")?.entries).toEqual([]);
    expect(result.sections.find((s) => s.id === "research")?.entries.map(resumeEntryKey)).toEqual([
      "acme",
      "prior",
      "undated",
    ]);
    expect(target.entries.map(resumeEntryKey)).toEqual(["prior", "undated"]);
  });

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

it("shows the skills a bullet already shows and keeps Extra skills collapsed", async () => {
  await editor();
  fireEvent.click(screen.getByRole("button", { name: "Expand Acme · Engineer" }));
  const experience = section("experience");
  expect(await experience.findByText("tooling")).toBeInTheDocument();
  expect(experience.getByText("Skills it shows:")).toBeInTheDocument();
  const extra = experience.getByText("Extra skills (1)").closest("details")!;
  expect(extra).not.toHaveAttribute("open");
  expect(experience.queryByText(/Suggest tags/)).not.toBeInTheDocument();
});

it("undoes and redoes a move with the keyboard outside text fields only", async () => {
  await editor();
  fireEvent.click(screen.getByRole("button", { name: "Expand Acme · Engineer" }));
  fireEvent.change(screen.getByRole("combobox", { name: "Move Acme · Engineer to section" }), {
    target: { value: "research" },
  });
  expect(screen.getByRole("status")).toHaveTextContent("Moved entry to “Research”");
  const company = section("research").getByRole("textbox", { name: "Company" });
  fireEvent.keyDown(company, { key: "z", ctrlKey: true });
  expect(section("research").queryByRole("textbox", { name: "Company" })).toBeInTheDocument();
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true });
  expect(section("research").queryByRole("textbox", { name: "Company" })).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Undid: Moved entry to “Research”");
  fireEvent.keyDown(document.body, { key: "Z", ctrlKey: true, shiftKey: true });
  expect(section("research").getByRole("textbox", { name: "Company" })).toHaveValue("Acme");
});

it("filters entries by their text and hides sections with no match", async () => {
  await editor();
  const filter = screen.getByRole("textbox", { name: "Filter resume entries" });
  fireEvent.change(filter, { target: { value: "state university" } });
  expect(screen.getByRole("button", { name: "Expand State University" })).toBeInTheDocument();
  expect(document.getElementById("resume-section-experience")).not.toBeVisible();
  fireEvent.change(filter, { target: { value: "no such words" } });
  expect(screen.getByText("No entries match “no such words”.")).toBeInTheDocument();
  fireEvent.keyDown(filter, { key: "Escape" });
  expect(filter).toHaveValue("");
  expect(document.getElementById("resume-section-experience")).toBeVisible();
});
