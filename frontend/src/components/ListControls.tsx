/**
 * Shared move / remove / add controls for master-resume editor lists.
 */

import { useConfirm } from "../state/confirmState";

type EntryControlsProps = {
  index: number;
  total: number;
  /** When true, removing asks for confirmation. */
  hasContent: boolean;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
  /** Optional short label for the confirm dialog, e.g. company name. */
  label?: string;
  /** When false, the move buttons are omitted entirely — used for fixed-order lists
   * that cannot be reordered. Defaults to true. Section order is editable here on the
   * Master resume tab; the Tailor tab's include panel is only a per-run override. */
  canMove?: boolean;
};

/**
 * Move-up, move-down, and remove buttons for one list row.
 * Blank rows delete silently; rows with content ask first.
 */
export function EntryControls({
  index,
  total,
  hasContent,
  onMove,
  onRemove,
  label,
  canMove = true,
}: EntryControlsProps) {
  const { confirm } = useConfirm();

  async function handleRemove() {
    if (hasContent) {
      const what = label?.trim() || "this entry";
      const ok = await confirm({
        title: "Remove entry",
        message: `Remove ${what}?`,
        confirmLabel: "Remove",
        tone: "danger",
      });
      if (!ok) return;
    }
    onRemove(index);
  }

  return (
    <div className="flex shrink-0 items-center gap-1">
      {canMove && (
        <>
          <button
            type="button"
            title="Move up"
            aria-label="Move up"
            disabled={index === 0}
            onClick={() => onMove(index, index - 1)}
            className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-30"
          >
            ↑
          </button>
          <button
            type="button"
            title="Move down"
            aria-label="Move down"
            disabled={index >= total - 1}
            onClick={() => onMove(index, index + 1)}
            className="rounded border border-line px-2 py-0.5 text-xs disabled:opacity-30"
          >
            ↓
          </button>
        </>
      )}
      <button
        type="button"
        title="Remove"
        onClick={() => void handleRemove()}
        className="rounded border border-line px-2 py-0.5 text-xs text-danger hover:border-danger"
      >
        Remove
      </button>
    </div>
  );
}

type AddButtonProps = {
  label: string;
  onClick: () => void;
};

/** Secondary-styled button that appends a blank row. */
export function AddButton({ label, onClick }: AddButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md border border-dashed border-line px-3 py-2 text-sm font-medium text-ink-muted hover:border-accent hover:text-accent"
    >
      {label}
    </button>
  );
}
