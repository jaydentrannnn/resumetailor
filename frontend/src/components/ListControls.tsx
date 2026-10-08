import { buttonClass } from "../lib/buttonClass";
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
            className={buttonClass("ghost", "sm", "min-w-9 px-2")}
          >
            ↑
          </button>
          <button
            type="button"
            title="Move down"
            aria-label="Move down"
            disabled={index >= total - 1}
            onClick={() => onMove(index, index + 1)}
            className={buttonClass("ghost", "sm", "min-w-9 px-2")}
          >
            ↓
          </button>
        </>
      )}
      <button
        type="button"
        title="Remove"
        onClick={() => onRemove(index)}
        className={buttonClass("danger", "sm")}
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
    <button type="button" onClick={onClick} className={buttonClass("secondary", "sm")}>
      {label}
    </button>
  );
}
