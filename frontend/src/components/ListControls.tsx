/**
 * Shared move / remove / add controls for master-resume editor lists.
 */

type EntryControlsProps = {
  index: number;
  total: number;
  onMove: (from: number, to: number) => void;
  /**
   * Removes row `index` immediately — nothing in this editor persists until the
   * explicit Save button, so this is optimistic; the caller is responsible for
   * registering an Undo toast (`pushUndo`) before applying the removal.
   */
  onRemove: (index: number) => void;
  /** When false, the move buttons are omitted entirely — used for fixed-order lists
   * that cannot be reordered. Defaults to true. Section order is editable here on the
   * Master resume tab; the Tailor tab's include panel is only a per-run override. */
  canMove?: boolean;
};

/** Move-up, move-down, and remove buttons for one list row. */
export function EntryControls({
  index,
  total,
  onMove,
  onRemove,
  canMove = true,
}: EntryControlsProps) {
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
            className="flex min-h-6 min-w-6 items-center justify-center rounded border border-line text-xs disabled:opacity-30"
          >
            ↑
          </button>
          <button
            type="button"
            title="Move down"
            aria-label="Move down"
            disabled={index >= total - 1}
            onClick={() => onMove(index, index + 1)}
            className="flex min-h-6 min-w-6 items-center justify-center rounded border border-line text-xs disabled:opacity-30"
          >
            ↓
          </button>
        </>
      )}
      <button
        type="button"
        title="Remove"
        onClick={() => onRemove(index)}
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
