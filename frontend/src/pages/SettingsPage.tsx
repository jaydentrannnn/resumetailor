import { useEffect, useState } from "react";
import {
  type LibraryAliasImpact,
  type LibraryPack,
  LibraryApprovalConflict,
  fetchLibraryPack,
} from "../api";
import { ChipListField } from "../components/ChipListField";
import { KeyValueListField } from "../components/KeyValueListField";
import { PackEditor } from "../components/library/PackEditor";
import { useLibraryState } from "../state/libraryState";

/**
 * Settings tab: manage the tag-alias and verb-family vocabulary that JD matching and
 * opening-verb variety checking draw on. Three sections: Packs (select which
 * built-in/user-authored vocabulary bundles are active), Your additions (per-profile
 * overrides layered on top), and Suggestions (LLM-drafted additions awaiting approval).
 */
export function SettingsPage() {
  return (
    <div className="space-y-6">
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
  const [editingPackId, setEditingPackId] = useState<string | null | "new">(null);
  const [expandedPackId, setExpandedPackId] = useState<string | null>(null);

  function togglePack(id: string, on: boolean) {
    const next = on ? [...enabledPacks, id] : enabledPacks.filter((p) => p !== id);
    void setEnabled(next);
  }

  function toggleExpanded(id: string) {
    setExpandedPackId((current) => (current === id ? null : id));
  }

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold">Packs</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Vocabulary bundles for tag-spelling matches and opening-verb variety.
            Composed in the order enabled below — a later pack wins a conflicting
            alias or verb.
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
            const expanded = expandedPackId === pack.id;
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
                    <span>
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{pack.label}</span>
                        {pack.builtin && (
                          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-accent">
                            Starter
                          </span>
                        )}
                        {pack.customized && (
                          <span className="rounded-full bg-paper px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-ink-muted">
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
                      onClick={() => toggleExpanded(pack.id)}
                      disabled={busy}
                      className="text-ink-muted underline-offset-2 hover:text-accent hover:underline disabled:opacity-50"
                    >
                      {expanded ? "Hide items" : "View items"}
                    </button>
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
                        onClick={() => {
                          if (
                            window.confirm(
                              `Reset "${pack.label}" to its starter contents? Your edits will be discarded.`,
                            )
                          ) {
                            void resetPack(pack.id);
                            if (expandedPackId === pack.id) setExpandedPackId(null);
                          }
                        }}
                        disabled={busy}
                        className="text-ink-muted underline-offset-2 hover:text-danger hover:underline disabled:opacity-50"
                      >
                        Reset to starter
                      </button>
                    )}
                    {!pack.builtin && (
                      <button
                        type="button"
                        onClick={() => {
                          if (window.confirm(`Delete the "${pack.label}" pack?`)) {
                            void deletePack(pack.id);
                            if (expandedPackId === pack.id) setExpandedPackId(null);
                          }
                        }}
                        disabled={busy}
                        className="text-ink-muted underline-offset-2 hover:text-danger hover:underline disabled:opacity-50"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
                {expanded && <PackItemsViewer packId={pack.id} />}
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

/**
 * Read-only, scrollable list of one pack's aliases and verb families. Loaded lazily
 * when the parent row expands.
 */
function PackItemsViewer({ packId }: { packId: string }) {
  const [pack, setPack] = useState<LibraryPack | null>(null);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPack(null);
    fetchLibraryPack(packId)
      .then((loaded) => {
        if (!cancelled) setPack(loaded);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [packId]);

  const needle = filter.trim().toLowerCase();
  const aliasRows = pack
    ? Object.entries(pack.tag_aliases).filter(
        ([alias, canonical]) =>
          !needle ||
          alias.toLowerCase().includes(needle) ||
          canonical.toLowerCase().includes(needle),
      )
    : [];
  const verbRows = pack
    ? Object.entries(pack.verb_families).filter(
        ([family, verbs]) =>
          !needle ||
          family.toLowerCase().includes(needle) ||
          verbs.some((verb) => verb.toLowerCase().includes(needle)),
      )
    : [];

  return (
    <div className="mt-3 ml-7 rounded-lg border border-line bg-paper/40 p-3">
      {loading ? (
        <p className="text-xs text-ink-muted">Loading items…</p>
      ) : error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : pack ? (
        <>
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter aliases and verbs…"
            className="field mb-3 text-xs"
          />
          <div className="max-h-64 space-y-3 overflow-y-auto pr-1 text-xs">
            {aliasRows.length > 0 && (
              <div>
                <p className="mb-1 font-medium text-ink-muted">Tag aliases</p>
                <ul className="space-y-0.5">
                  {aliasRows.map(([alias, canonical]) => (
                    <li key={alias} className="font-mono text-[0.7rem]">
                      {alias} → {canonical}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {verbRows.length > 0 && (
              <div>
                <p className="mb-1 font-medium text-ink-muted">Verb families</p>
                <ul className="space-y-0.5">
                  {verbRows.map(([family, verbs]) => (
                    <li key={family} className="font-mono text-[0.7rem]">
                      {family}: {verbs.join(", ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {aliasRows.length === 0 && verbRows.length === 0 && (
              <p className="text-ink-muted">
                {needle ? "No items match the filter." : "This pack has no items yet."}
              </p>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

function OverridesSection() {
  const { overrides, busy, setOverrides } = useLibraryState();

  return (
    <section className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <h2 className="font-display text-xl font-semibold">Your additions</h2>
      <p className="mt-1 text-sm text-ink-muted">
        Per-profile edits layered on top of whichever packs are enabled above — these
        always win over a pack, and a removal always wins over an addition.
      </p>

      <fieldset disabled={busy} className="mt-4 space-y-5">
        <KeyValueListField
          label="Added aliases (spelling → your canonical tag)"
          keyPlaceholder="e.g. pg"
          valuePlaceholder="e.g. postgresql"
          items={overrides.tag_aliases}
          onChange={(next) => void setOverrides({ ...overrides, tag_aliases: next })}
        />
        <ChipListField
          label="Removed aliases (suppress one from an enabled pack)"
          items={overrides.tag_aliases_removed}
          onChange={(next) =>
            void setOverrides({ ...overrides, tag_aliases_removed: next })
          }
          placeholder="Type an alias key and press Enter"
        />
        <KeyValueListField
          label="Added verb overrides (verb → family)"
          keyPlaceholder="e.g. triaged"
          valuePlaceholder="e.g. analyse"
          items={overrides.verb_families}
          onChange={(next) => void setOverrides({ ...overrides, verb_families: next })}
        />
        <ChipListField
          label="Removed verbs (suppress one from an enabled pack)"
          items={overrides.verb_families_removed}
          onChange={(next) =>
            void setOverrides({ ...overrides, verb_families_removed: next })
          }
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
          <h2 className="font-display text-xl font-semibold">Suggestions</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Drafted from your resume's own near-miss keyword gaps and opening verbs no
            family claims. Nothing here takes effect until you approve it into a pack.
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
                          <span className="rounded-full bg-warn-soft px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-warn">
                            Rewrites {impact!.affected_tags.length} tag
                            {impact!.affected_tags.length === 1 ? "" : "s"}
                          </span>
                        ) : (
                          <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-accent">
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
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50"
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
              className="rounded-md bg-warn px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
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
