import { ChipListField } from "../../components/ChipListField";
import { useConfirm } from "../../state/confirmState";
import { type MasterResume, countTagUsage, removeTagFromResume } from "../../lib/resumeEdit";

export function TagVocabularyPanel({
  resume,
  onChange,
}: {
  resume: MasterResume;
  onChange: (r: MasterResume) => void;
}) {
  /**
   * Manage the shared tag option list. Removing an in-use option strips it from
   * every bullet after confirmation — tags are the fabrication guard's whitelist.
   */
  const { confirm } = useConfirm();
  const vocab = resume.tag_vocabulary ?? [];

  async function applyVocabulary(next: string[]) {
    /** Diff against current vocab; removals strip the tag from every bullet. */
    const nextLower = new Set(next.map((t) => t.toLowerCase()));
    const removed = vocab.filter((t) => !nextLower.has(t.toLowerCase()));
    const inUse = removed
      .map((tag) => ({ tag, used: countTagUsage(resume, tag) }))
      .filter((r) => r.used > 0);

    if (inUse.length > 0) {
      const lines = inUse.map((r) => `• "${r.tag}" on ${r.used} bullet(s)`).join("\n");
      const ok = await confirm({
        title: "Remove tags from bullets?",
        message: `These tags are in use and will be stripped from every bullet that uses them:\n\n${lines}`,
        confirmLabel: "Remove from vocabulary and bullets",
        tone: "danger",
      });
      if (!ok) return;
    }

    let updated: MasterResume = { ...resume, tag_vocabulary: next };
    for (const tag of removed) {
      updated = removeTagFromResume(updated, tag);
      updated = {
        ...updated,
        tag_vocabulary: next.filter((t) => t.toLowerCase() !== tag.toLowerCase()),
      };
    }
    onChange(updated);
  }

  return (
    <details className="group rounded-xl border border-line bg-panel p-5 shadow-sm">
      {/* Closed by default — this is a shared option list (settings), not resume
          content, and at ~150 tags it would otherwise dominate the page above
          Contact and every actual section. `list-none` + a manual marker keeps
          the disclosure triangle in the design system's own voice instead of the
          browser default. */}
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
        <span>
          <span className="font-display text-lg font-semibold">Tag options</span>
          <span className="ml-2 text-sm text-ink-muted">
            {vocab.length} tag{vocab.length === 1 ? "" : "s"}
          </span>
        </span>
        <span className="text-ink-muted transition-transform duration-[var(--dur-short)] ease-out group-open:rotate-180">
          ▾
        </span>
      </summary>
      <p className="mt-2 text-sm text-ink-muted">
        Shared list for bullet tags. Adding a tag on a bullet also adds it here; removing an option
        strips it from every bullet that uses it.
      </p>
      <div className="mt-3">
        <ChipListField
          label="Vocabulary"
          items={vocab}
          onChange={(items) => void applyVocabulary(items)}
          placeholder="Add a tag option"
        />
      </div>
    </details>
  );
}
