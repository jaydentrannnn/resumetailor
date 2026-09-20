import { useEffect, useRef, useState } from "react";
import {
  type LibraryAliasImpact,
  type LibraryOverrides,
  LibraryApprovalConflict,
} from "../api";
import { ChipListField } from "../components/ChipListField";
import { KeyValueListField } from "../components/KeyValueListField";
import { PackEditor } from "../components/library/PackEditor";
import { useConfirm } from "../state/confirmState";
import { useLibraryState } from "../state/libraryState";

/**
 * Vocabulary tab: manage the tag-alias and verb-family vocabulary that JD matching and
 * opening-verb variety checking draw on. Three layers, composed top to bottom: Packs
 * (which built-in/user-authored bundles are active, and in what order), Your additions
 * (per-profile overrides that always win over a pack), and Suggestions (LLM-drafted
 * additions awaiting approval into a pack, i.e. feeding back into layer one).
 */
export function VocabularyPage() {
  const { effective } = useLibraryState();
  return (
    <div className="space-y-6">
      <h1 className="sr-only">Vocabulary</h1>
      <p className="text-sm text-ink-muted">
        Active vocabulary:{" "}
        <span className="font-medium text-ink">
          {effective.tag_alias_count} alias{effective.tag_alias_count === 1 ? "" : "es"} &middot;{" "}
          {effective.verb_count} verb{effective.verb_count === 1 ? "" : "s"}
        </span>
      </p>
      <PacksSection />
      <OverridesSection />
      <SuggestionsSection />
    </div>
  );
}

function PacksSection() {
  const {
    packs,
    enabledPacks,
    diagnostics,
    loading,
    busy,
    error,
    setEnabled,
    deletePack,
    resetPack,
  } = useLibraryState();
  const { confirm } = useConfirm();
  const [editingPackId, setEditingPackId] = useState<string | null | "new">(null);

  function togglePack(id: string, on: boolean) {
    const next = on ? [...enabledPacks, id] : enabledPacks.filter((p) => p !== id);
    void setEnabled(next);
  }

  async function handleReset(packId: string, packLabel: string) {
    const ok = await confirm({
      title: "Reset pack",
      message: `Reset "${packLabel}" to its starter contents? Your edits will be discarded.`,
      confirmLabel: "Reset to starter",
      tone: "danger",
    });
    if (!ok) return;
    void resetPack(packId);
  }

  async function handleDelete(packId: string, packLabel: string) {
    const ok = await confirm({
      title: "Delete pack",
      message: `Delete the "${packLabel}" pack?`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    void deletePack(packId);
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">1. Packs</h2>
          <p className="mt-1 text-sm text-ink-muted">
            The base layers, composed in the order enabled below — a later pack wins a
            conflicting alias or verb.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditingPackId("new")}
          disabled={busy}
          className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
        >
          New pack
        </button>
      </div>

      {error && (
        <p className="mt-3 whitespace-pre-line rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-4 text-sm text-ink-muted">Loading packs…</p>
      ) : (
        <ul className="mt-4 divide-y divide-line">
          {packs.map((pack) => {
            const enabled = enabledPacks.includes(pack.id);
            return (
              <li key={pack.id} className="py-3">
                <div className="flex items-start justify-between gap-3">
                  <label className="flex flex-1 cursor-pointer items-start gap-3">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => togglePack(pack.id, e.target.checked)}
                      disabled={busy}
                      className="mt-1 accent-[var(--color-accent)]"
                    />
                    {/* max-w-xl keeps the text column from stretching edge-to-edge on a
                        wide screen — at full width a long description pushed "Edit"
                        ~900px away from the name it acts on. */}
                    <span className="max-w-xl">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{pack.label}</span>
                        {pack.builtin && (
                          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-micro font-semibold uppercase tracking-wide text-accent">
                            Starter
                          </span>
                        )}
                        {pack.customized && (
                          <span className="rounded-full bg-paper px-2 py-0.5 text-micro font-semibold uppercase tracking-wide text-ink-muted">
                            Edited
                          </span>
                        )}
                      </span>
                      {pack.description && (
                        <span className="mt-0.5 block text-xs text-ink-muted">
                          {pack.description}
                        </span>
                      )}
                      <span className="mt-0.5 block text-xs text-ink-muted">
                        {pack.tag_alias_count} aliases &middot; {pack.verb_count} verbs
                      </span>
                    </span>
                  </label>
                  <div className="flex flex-none flex-wrap items-center justify-end gap-2 text-xs">
                    <button
                      type="button"
                      onClick={() => setEditingPackId(pack.id)}
                      disabled={busy}
                      className="text-ink-muted underline-offset-2 hover:text-accent hover:underline disabled:opacity-50"
                    >
                      Edit
                    </button>
                    {pack.builtin && pack.customized && (
                      <button
                        type="button"
                        onClick={() => void handleReset(pack.id, pack.label)}
                        disabled={busy}
                        className="text-ink-muted underline-offset-2 hover:text-danger hover:underline disabled:opacity-50"
                      >
                        Reset to starter
                      </button>
                    )}
                    {!pack.builtin && (
                      <button
                        type="button"
                        onClick={() => void handleDelete(pack.id, pack.label)}
                        disabled={busy}
                        className="text-ink-muted underline-offset-2 hover:text-danger hover:underline disabled:opacity-50"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {diagnostics.length > 0 && (
        <div className="mt-4 space-y-1 rounded-md bg-paper/60 px-3 py-2">
          {diagnostics.map((d, i) => (
            <p key={i} className="text-xs text-ink-muted">
              {d}
            </p>
          ))}
        </div>
      )}

      {editingPackId !== null && (
        <PackEditor
          packId={editingPackId === "new" ? null : editingPackId}
          onClose={() => setEditingPackId(null)}
        />
      )}
    </section>
  );
}

function sameOverrides(a: LibraryOverrides, b: LibraryOverrides): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Debounce between a keystroke/chip edit and the `PUT` it triggers — long enough that
 * a burst of edits (typing a value, then tabbing to add a chip) collapses into one
 * write, short enough that "did my edit save" never feels uncertain. */
const SAVE_DEBOUNCE_MS = 600;

function OverridesSection() {
  const { overrides, setOverrides } = useLibraryState();

  // Local draft + a synchronous ref mirror: two edits made in the same tick (e.g. a
  // value blur immediately followed by a chip add, before React re-renders) must both
  // land on the debounced write, not have the second overwrite the first from a stale
  // closure over `draft` state.
  const draftRef = useRef<LibraryOverrides>(overrides);
  const lastSynced = useRef<LibraryOverrides>(overrides);
  const [draft, setDraft] = useState<LibraryOverrides>(overrides);
  const [saveState, setSaveState] = useState<"idle" | "pending" | "saving">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Render-phase adjustment (not an effect, which would paint one stale frame first):
  // re-seed only when the context's value has genuinely changed from what this section
  // itself last sent — a PUT response that echoes back a deep-equal-but-new object must
  // not clobber an edit still mid-debounce.
  if (!sameOverrides(overrides, lastSynced.current)) {
    lastSynced.current = overrides;
    draftRef.current = overrides;
    setDraft(overrides);
  }

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  function updateDraft(patch: Partial<LibraryOverrides>) {
    const next = { ...draftRef.current, ...patch };
    draftRef.current = next;
    setDraft(next);
    setSaveState("pending");
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      const toSend = draftRef.current;
      setSaveState("saving");
      lastSynced.current = toSend;
      void setOverrides(toSend).finally(() => setSaveState("idle"));
    }, SAVE_DEBOUNCE_MS);
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-display text-xl font-semibold">2. Your additions</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Per-profile edits layered on top of whichever packs are enabled above — these
            always win over a pack, and a removal always wins over an addition.
          </p>
        </div>
        {saveState !== "idle" && (
          <span className="text-xs text-ink-muted">
            {saveState === "pending" ? "Unsaved…" : "Saving…"}
          </span>
        )}
      </div>

      <fieldset className="mt-4 space-y-5">
        <KeyValueListField
          label="Added aliases (spelling → your canonical tag)"
          keyPlaceholder="e.g. pg"
          valuePlaceholder="e.g. postgresql"
          items={draft.tag_aliases}
          onChange={(next) => updateDraft({ tag_aliases: next })}
        />
        <ChipListField
          label="Removed aliases (suppress one from an enabled pack)"
          items={draft.tag_aliases_removed}
          onChange={(next) => updateDraft({ tag_aliases_removed: next })}
          placeholder="Type an alias key and press Enter"
        />
        <div>
          <KeyValueListField
            label="Added verb overrides (verb → family)"
            keyPlaceholder="e.g. triaged"
            valuePlaceholder="e.g. analyse"
            items={draft.verb_families}
            onChange={(next) => updateDraft({ verb_families: next })}
          />
          <p className="mt-1 text-xs text-ink-muted">
            One family per verb — the inverse of a pack's own family &rarr; verbs list.
          </p>
        </div>
        <ChipListField
          label="Removed verbs (suppress one from an enabled pack)"
          items={draft.verb_families_removed}
          onChange={(next) => updateDraft({ verb_families_removed: next })}
          placeholder="Type a verb and press Enter"
        />
      </fieldset>
    </section>
  );
}

function SuggestionsSection() {
  const {
    packs,
    proposals,
    proposalWarning,
    busy,
    generating,
    error,
    previewImpact,
    generateProposals,
    approveProposals,
    rejectProposals,
  } = useLibraryState();

  const [jdText, setJdText] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [impactByAlias, setImpactByAlias] = useState<Record<string, LibraryAliasImpact>>({});
  const [conflict, setConflict] = useState<{
    ids: string[];
    targetPackId: string;
    message: string;
    impact: LibraryAliasImpact[];
  } | null>(null);

  const targetPacks = packs;
  const [targetPackId, setTargetPackId] = useState("");

  useEffect(() => {
    if (!targetPackId && targetPacks.length > 0) setTargetPackId(targetPacks[0].id);
  }, [targetPacks, targetPackId]);

  useEffect(() => {
    // Additive-vs-rewrite impact only applies to tag-alias proposals; verb-family
    // proposals never rewrite existing content, so they carry no badge to compute.
    const aliasEntries = proposals
      .filter((p) => p.kind === "tag_alias" && p.alias && p.canonical)
      .map((p) => [p.alias as string, p.canonical as string] as const);
    if (aliasEntries.length === 0) {
      setImpactByAlias({});
      return;
    }
    let cancelled = false;
    void previewImpact(Object.fromEntries(aliasEntries)).then((impacts) => {
      if (cancelled) return;
      setImpactByAlias(Object.fromEntries(impacts.map((i) => [i.alias, i])));
    });
    return () => {
      cancelled = true;
    };
  }, [proposals, previewImpact]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function doApprove(ids: string[], acknowledgeRewrites: boolean) {
    if (!targetPackId) return;
    try {
      await approveProposals(ids, targetPackId, acknowledgeRewrites);
      setSelected(new Set());
      setConflict(null);
    } catch (err) {
      if (err instanceof LibraryApprovalConflict) {
        setConflict({ ids, targetPackId, message: err.message, impact: err.impact });
      }
    }
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">3. Suggestions</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Drafted from your resume's own near-miss keyword gaps and opening verbs no
            family claims. Nothing here takes effect until you approve it into a pack
            above.
          </p>
        </div>
      </div>

      <div className="mt-4 space-y-2">
        <label className="block text-sm">
          <span className="mb-1 block text-ink-muted">Job description (optional)</span>
          <textarea
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
            rows={3}
            placeholder="Paste a posting to also check its keywords against your tags…"
            className="field"
          />
        </label>
        <button
          type="button"
          onClick={() => void generateProposals(jdText)}
          disabled={generating}
          className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-accent hover:text-accent disabled:opacity-50"
        >
          {generating ? "Drafting suggestions…" : "Generate suggestions"}
        </button>
      </div>

      {error && (
        <p className="mt-3 whitespace-pre-line rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}
      {proposalWarning && (
        <p className="mt-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">
          {proposalWarning}
        </p>
      )}

      {proposals.length > 0 && (
        <>
          <ul className="mt-4 divide-y divide-line">
            {proposals.map((p) => {
              const impact = p.alias ? impactByAlias[p.alias] : undefined;
              const rewrites = impact && impact.affected_tags.length > 0;
              return (
                <li key={p.id} className="flex items-start gap-3 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(p.id)}
                    onChange={() => toggle(p.id)}
                    disabled={busy}
                    className="mt-1 accent-[var(--color-accent)]"
                  />
                  <div className="flex-1 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      {p.kind === "tag_alias" ? (
                        <span className="font-medium">
                          {p.alias} &rarr; {p.canonical}
                        </span>
                      ) : (
                        <span className="font-medium">
                          {p.verb} &rarr; {p.family}
                        </span>
                      )}
                      {p.kind === "tag_alias" &&
                        (rewrites ? (
                          <span className="rounded-full bg-warn-soft px-2 py-0.5 text-micro font-semibold uppercase tracking-wide text-warn">
                            Rewrites {impact!.affected_tags.length} tag
                            {impact!.affected_tags.length === 1 ? "" : "s"}
                          </span>
                        ) : (
                          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-micro font-semibold uppercase tracking-wide text-accent">
                            Additive
                          </span>
                        ))}
                    </div>
                    {p.rationale && (
                      <p className="mt-0.5 text-xs text-ink-muted">{p.rationale}</p>
                    )}
                    {rewrites && (
                      <p className="mt-0.5 text-xs text-ink-muted">
                        Affects: {impact!.affected_bullets.map(([label]) => label).join(", ")}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label className="text-sm">
              <span className="mr-2 text-ink-muted">Approve into</span>
              <select
                value={targetPackId}
                onChange={(e) => setTargetPackId(e.target.value)}
                className="field inline-block w-auto"
              >
                {targetPacks.length === 0 && <option value="">No packs available</option>}
                {targetPacks.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void doApprove([...selected], false)}
              disabled={busy || selected.size === 0 || !targetPackId}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent disabled:opacity-50"
            >
              Approve selected
            </button>
            <button
              type="button"
              onClick={() => void rejectProposals([...selected]).then(() => setSelected(new Set()))}
              disabled={busy || selected.size === 0}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-medium text-ink hover:border-danger hover:text-danger disabled:opacity-50"
            >
              Reject selected
            </button>
          </div>
        </>
      )}

      {conflict && (
        <div className="mt-4 space-y-3 rounded-lg border border-warn/40 bg-warn-soft/40 p-4">
          <p className="text-sm font-medium text-warn">{conflict.message}</p>
          <ul className="space-y-1 text-xs text-ink-muted">
            {conflict.impact.map((i) => (
              <li key={i.alias}>
                <span className="font-medium text-ink">{i.alias}</span> currently tags:{" "}
                {i.affected_bullets.map(([label]) => label).join(", ")}
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted">
            This permanently rewrites those tags the next time the master resume is
            saved. A backup will be saved first.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void doApprove(conflict.ids, true)}
              className="rounded-md bg-warn px-3 py-1.5 text-sm font-medium text-on-accent hover:brightness-95"
            >
              Approve anyway
            </button>
            <button
              type="button"
              onClick={() => setConflict(null)}
              className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-muted hover:border-accent hover:text-accent"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
