import { useState } from "react";
import { DataTable } from "../../components/TableControls";
import { PackEditor } from "../../components/library/PackEditor";
import { StatusChip, Tile } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { useConfirm } from "../../state/confirmState";
import { useLibraryState } from "../../state/libraryState";
export function PacksSection() {
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
    void setEnabled(next).catch(() => {});
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
    <Tile>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="rt-tile-title">Packs</h2>
          <p className="mt-1 text-sm text-ink-muted">
            The base layers, composed in the order enabled below — a later pack wins a conflicting
            alias or verb.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditingPackId("new")}
          disabled={busy}
          className={buttonClass("secondary", "sm")}
        >
          New pack
        </button>
      </div>

      {error && (
        <p className="mt-3 whitespace-pre-line rounded-sm bg-danger-soft px-3 py-2 text-xs text-danger">
          {error}
        </p>
      )}

      <div className="mt-5 bg-panel [&_thead]:bg-sunken">
        <DataTable
          bare
          rows={packs}
          id={(pack) => pack.id}
          selected={new Set()}
          onSelected={() => {}}
          selectable={false}
          sort=""
          direction="asc"
          onSort={() => {}}
          loading={loading}
          loadingText="Loading packs…"
          empty="No packs yet. Create a new pack to get started."
          columns={[
            {
              id: "pack",
              heading: "Pack",
              className: "w-[25%]",
              cell: (pack) => (
                <div className="space-y-2">
                  <span className="font-medium">{pack.label}</span>
                  <div className="flex flex-wrap gap-2">
                    {pack.builtin && <StatusChip tone="neutral">Starter</StatusChip>}
                    {pack.customized && <StatusChip tone="muted">Edited</StatusChip>}
                  </div>
                </div>
              ),
            },
            {
              id: "description",
              heading: "Field",
              className: "w-[30%]",
              cell: (pack) => <span className="text-xs text-ink-muted">{pack.description}</span>,
            },
            {
              id: "verbs",
              heading: "Verbs",
              cell: (pack) => <span className="font-mono">{pack.verb_count}</span>,
            },
            {
              id: "aliases",
              heading: "Aliases",
              cell: (pack) => <span className="font-mono">{pack.tag_alias_count}</span>,
            },
            {
              id: "on",
              heading: "On",
              cell: (pack) => (
                <input
                  type="checkbox"
                  aria-label={pack.label}
                  checked={enabledPacks.includes(pack.id)}
                  onChange={(e) => togglePack(pack.id, e.target.checked)}
                  disabled={busy}
                />
              ),
            },
            {
              id: "actions",
              heading: "Actions",
              className: "w-[20%]",
              cell: (pack) => (
                <div className="flex flex-wrap gap-1">
                  <button
                    type="button"
                    onClick={() => setEditingPackId(pack.id)}
                    disabled={busy}
                    className={buttonClass("ghost", "sm")}
                  >
                    Edit
                  </button>
                  {pack.builtin && pack.customized && (
                    <button
                      type="button"
                      onClick={() => void handleReset(pack.id, pack.label)}
                      disabled={busy}
                      className={buttonClass("ghost", "sm")}
                    >
                      Reset to starter
                    </button>
                  )}
                  {!pack.builtin && (
                    <button
                      type="button"
                      onClick={() => void handleDelete(pack.id, pack.label)}
                      disabled={busy}
                      className={buttonClass("danger", "sm")}
                    >
                      Delete
                    </button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </div>

      {diagnostics.length > 0 && (
        <div className="mt-4 space-y-1 border-t border-line pt-4">
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
    </Tile>
  );
}
