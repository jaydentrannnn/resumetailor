/**
 * Row-click selection shared by the data tables and the Sources list: a click anywhere
 * on a row (or a tapped card) ticks it, Shift-click ticks a range. Controls inside the
 * row keep their own click; the checkbox stays the keyboard and screen-reader path.
 */

/** Anything inside a row that does its own thing on click. */
const OWN_CLICK =
  'a, button, input, select, textarea, label, summary, [role="menu"], [role="menuitem"], ' +
  '[role="switch"], [contenteditable="true"], [data-row-select="off"]';

type ClickLike = {
  target: EventTarget | null;
  button: number;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  /** 2 for the second click of a double-click, and so on. */
  detail?: number;
};

/** Whether a click on a row should toggle it (not a control, not a text highlight). */
export function isRowSelectClick(event: ClickLike, row?: Element | null): boolean {
  if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey) return false;
  const target = event.target as Element | null;
  // A portal (a row's "…" menu) bubbles through React but sits outside the row's DOM.
  if (row && !(target && row.contains(target))) return false;
  const control = target?.closest?.(OWN_CLICK);
  // A control *around* the row is not the row's own control.
  if (control && (!row || row.contains(control))) return false;
  // Highlighting text to copy it ends in a click too: leave the selection alone. A quick
  // second click is a double-click, whose word highlight is no highlight of the person's.
  if ((event.detail ?? 1) > 1) return true;
  const highlighted = typeof window !== "undefined" ? window.getSelection?.()?.toString() : "";
  return !highlighted;
}

/**
 * A row's mousedown: Shift-click would highlight the text between the two clicks, and a
 * quick second click would highlight a word; neither is wanted on a selectable row.
 */
export function preventRowHighlight(event: {
  shiftKey: boolean;
  detail: number;
  preventDefault: () => void;
}): void {
  if (event.shiftKey || event.detail > 1) event.preventDefault();
}

/**
 * Shift-click from `anchor` to `target`: every eligible row between them (both ends
 * included, either direction) takes the anchor row's state, so a range can tick or
 * untick. Ids not in `ordered` (another page, another group) give null: a plain toggle.
 */
export function rangeSelect(
  selected: ReadonlySet<string>,
  ordered: readonly string[],
  eligible: (id: string) => boolean,
  anchor: string,
  target: string,
): Set<string> | null {
  const from = ordered.indexOf(anchor);
  const to = ordered.indexOf(target);
  if (from < 0 || to < 0) return null;
  const on = selected.has(anchor);
  const next = new Set(selected);
  for (let at = Math.min(from, to); at <= Math.max(from, to); at++) {
    const id = ordered[at];
    if (!eligible(id)) continue;
    if (on) next.add(id);
    else next.delete(id);
  }
  return next;
}

/** One toggle or a Shift range, remembering the anchor for the next Shift-click. */
export function clickSelect(
  selected: ReadonlySet<string>,
  ordered: readonly string[],
  eligible: (id: string) => boolean,
  anchor: { current: string | null },
  id: string,
  shift: boolean,
): Set<string> {
  const range =
    shift && anchor.current && anchor.current !== id
      ? rangeSelect(selected, ordered, eligible, anchor.current, id)
      : null;
  if (range) return range;
  anchor.current = id;
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
