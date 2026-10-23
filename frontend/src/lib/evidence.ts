import type {
  EvidenceAttribution,
  EvidenceKind,
  EvidenceProposal,
  EvidenceSource,
  EvidenceSourceKind,
} from "../api";
import type { MasterResume } from "./resumeEdit";
import type { Tone } from "./tone";

export const SOURCE_KIND_LABELS: Record<EvidenceSourceKind, string> = {
  github: "GitHub repository",
  syllabus: "Course syllabus",
  letter: "Reference letter",
  writeup: "Project write-up",
  other: "Document",
};

export const PROPOSAL_KIND_LABELS: Record<EvidenceKind, string> = {
  bullet: "Bullet",
  project: "New project",
  skill: "Skill",
  coursework: "Course",
};

/** Whose work a repository is, as a chip; documents have none. */
export function attributionChip(
  source: Pick<EvidenceSource, "attribution" | "commit_share">,
): { label: string; tone: Tone } | null {
  const share =
    source.commit_share === null ? "" : ` · ${Math.round(source.commit_share * 100)}% of commits`;
  const chips: Record<EvidenceAttribution, { label: string; tone: Tone } | null> = {
    own: { label: `Your repository${share}`, tone: "done" },
    contributed: { label: `You contributed${share}`, tone: "ready" },
    fork: { label: "Fork · not your work", tone: "muted" },
    unknown: { label: "Your commits not found", tone: "attention" },
    "": null,
  };
  return chips[source.attribution];
}

/** One line under a source: scanned or not, what the guard dropped. */
export function sourceStatus(source: EvidenceSource): string {
  if (source.attribution === "fork") return "Forks are never read as your work.";
  if (!source.scanned_at) return "Not scanned yet.";
  const day = source.scanned_at.slice(0, 10);
  if (!source.dropped) return `Scanned ${day}.`;
  const reasons = Object.entries(source.drop_reasons)
    .map(([reason, n]) => `${n} ${reason}`)
    .join(", ");
  return `Scanned ${day}. ${source.dropped} item(s) dropped because the source didn't support them${reasons ? ` (${reasons})` : ""}.`;
}

export type ProposalGroup = { source: EvidenceSource | null; items: EvidenceProposal[] };

/** Pending items first, grouped by source in the sources' order; decided items after. */
export function groupProposals(
  sources: EvidenceSource[],
  proposals: EvidenceProposal[],
): { pending: ProposalGroup[]; decided: EvidenceProposal[] } {
  const pending = proposals.filter((p) => p.state === "pending");
  const groups: ProposalGroup[] = sources
    .map((source) => ({ source, items: pending.filter((p) => p.source_id === source.id) }))
    .filter((group) => group.items.length > 0);
  const orphans = pending.filter((p) => !sources.some((s) => s.id === p.source_id));
  if (orphans.length) groups.push({ source: null, items: orphans });
  return { pending: groups, decided: proposals.filter((p) => p.state !== "pending") };
}

export const STATE_LABELS: Record<EvidenceProposal["state"], string> = {
  pending: "Waiting",
  added: "Added to resume",
  matching_only: "Matching only",
  dismissed: "Dismissed",
};

export type EntryOption = { id: string; label: string; kind: "experience" | "project" };

/** Every experience and project entry, for the "goes to" picker. */
export function entryOptions(resume: MasterResume | null): EntryOption[] {
  if (!resume) return [];
  return resume.sections.flatMap((section): EntryOption[] => {
    if (section.kind === "experience")
      return section.entries.map((e) => ({
        id: e.id,
        label: [e.title, e.company].filter(Boolean).join(", ") || e.id,
        kind: "experience",
      }));
    if (section.kind === "project")
      return section.entries.map((e) => ({ id: e.id, label: e.name || e.id, kind: "project" }));
    return [];
  });
}

export function entryLabel(resume: MasterResume | null, id: string): string {
  return entryOptions(resume).find((e) => e.id === id)?.label ?? id;
}

export function skillGroups(resume: MasterResume | null): string[] {
  if (!resume) return [];
  return resume.sections.flatMap((s) => (s.kind === "skills" ? s.entries.map((g) => g.label) : []));
}

export function schools(resume: MasterResume | null): string[] {
  if (!resume) return [];
  return resume.sections.flatMap((s) =>
    s.kind === "education" ? s.entries.map((e) => e.school || "School") : [],
  );
}

export function projectSections(resume: MasterResume | null): { id: string; title: string }[] {
  if (!resume) return [];
  return resume.sections
    .filter((s) => s.kind === "project")
    .map((s) => ({ id: s.id, title: s.title }));
}

/** Skills a bullet could take as Extra skills: the new project's tech, or a GitHub
 * repository's languages. Never ticked by default. */
export function skillChoices(
  proposal: EvidenceProposal,
  source: EvidenceSource | undefined,
): string[] {
  const seen = new Set<string>();
  return [...(proposal.new_project?.tech ?? []), ...(source?.languages ?? [])].filter((skill) => {
    const key = skill.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
