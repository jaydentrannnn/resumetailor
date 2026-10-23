import { describe, expect, it } from "vitest";
import type { EvidenceProposal, EvidenceSource } from "../api";
import {
  attributionChip,
  entryOptions,
  groupProposals,
  skillChoices,
  sourceStatus,
} from "./evidence";
import type { MasterResume } from "./resumeEdit";

const source = (over: Partial<EvidenceSource> = {}): EvidenceSource => ({
  id: "s1",
  kind: "github",
  title: "jordan/chef",
  url: null,
  added_at: "",
  flags: [],
  attribution: "own",
  commit_share: 0.92,
  languages: ["Python", "HTML"],
  scanned_at: "",
  dropped: 0,
  drop_reasons: {},
  model: "",
  chars: 100,
  ...over,
});

const proposal = (over: Partial<EvidenceProposal> = {}): EvidenceProposal => ({
  id: "e1",
  source_id: "s1",
  kind: "bullet",
  target_entry_id: "acme",
  new_project: null,
  text: "Built a thing",
  excerpt: "We built a thing.",
  basis: "stated",
  question: "",
  state: "pending",
  decided_at: "",
  added_to: "",
  ...over,
});

describe("evidence helpers", () => {
  it("labels whose work a repository is", () => {
    expect(attributionChip(source())).toEqual({
      label: "Your repository · 92% of commits",
      tone: "done",
    });
    expect(attributionChip(source({ attribution: "fork", commit_share: null }))?.label).toBe(
      "Fork · not your work",
    );
    expect(attributionChip(source({ kind: "letter", attribution: "" }))).toBeNull();
  });

  it("says when a source was scanned and why items were dropped", () => {
    expect(sourceStatus(source())).toBe("Not scanned yet.");
    expect(
      sourceStatus(
        source({
          scanned_at: "2026-10-23T10:00:00+00:00",
          dropped: 2,
          drop_reasons: { "term not in excerpt": 2 },
        }),
      ),
    ).toBe(
      "Scanned 2026-10-23. 2 item(s) dropped because the source didn't support them (2 term not in excerpt).",
    );
  });

  it("groups waiting items by source and keeps decided ones apart", () => {
    const sources = [source(), source({ id: "s2", title: "Letter" })];
    const { pending, decided } = groupProposals(sources, [
      proposal({ id: "a", source_id: "s2" }),
      proposal({ id: "b" }),
      proposal({ id: "c", state: "dismissed" }),
      proposal({ id: "d", source_id: "gone" }),
    ]);
    expect(pending.map((g) => [g.source?.id ?? null, g.items.map((p) => p.id)])).toEqual([
      ["s1", ["b"]],
      ["s2", ["a"]],
      [null, ["d"]],
    ]);
    expect(decided.map((p) => p.id)).toEqual(["c"]);
  });

  it("lists experience and project entries to place a bullet", () => {
    const resume = {
      sections: [
        {
          id: "x",
          kind: "experience",
          title: "Experience",
          entries: [{ id: "acme", company: "Acme", title: "Intern", bullets: [] }],
        },
        {
          id: "p",
          kind: "project",
          title: "Projects",
          entries: [{ id: "proj_chef", name: "Chef", bullets: [] }],
        },
        { id: "s", kind: "skills", title: "Skills", entries: [{ label: "Tools", items: [] }] },
      ],
    } as unknown as MasterResume;
    expect(entryOptions(resume)).toEqual([
      { id: "acme", label: "Intern, Acme", kind: "experience" },
      { id: "proj_chef", label: "Chef", kind: "project" },
    ]);
  });

  it("offers a project's tech and the repository's languages once each", () => {
    const item = proposal({
      new_project: { name: "Chef", tech: ["Flask", "python"], url: "", start: "", end: "" },
    });
    expect(skillChoices(item, source())).toEqual(["Flask", "python", "HTML"]);
  });
});
