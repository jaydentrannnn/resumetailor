/**
 * The desktop app's own text menu (the browser's menu is switched off in the app
 * window): which of Cut / Copy / Paste / Select all apply where the user right-clicked.
 */
export type TextMenuItem = "cut" | "copy" | "paste" | "selectAll";

export type TextMenuTarget = {
  /** An input, textarea or contenteditable that accepts typing. */
  editable: boolean;
  /** Text is selected (in the field, or on the page). */
  hasSelection: boolean;
};

/** Text inputs that hold selectable text; checkboxes, buttons etc. do not. */
const TEXT_INPUT_TYPES = new Set(["", "text", "search", "email", "url", "tel", "password", "number"]);

export function editableElement(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  const field = target.closest<HTMLElement>("input, textarea, [contenteditable='true'], [contenteditable='']");
  if (!field) return null;
  if (field instanceof HTMLInputElement) {
    if (!TEXT_INPUT_TYPES.has(field.type) || field.readOnly || field.disabled) return null;
  }
  if (field instanceof HTMLTextAreaElement && (field.readOnly || field.disabled)) return null;
  return field;
}

export function fieldHasSelection(field: HTMLElement | null): boolean {
  if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
    try {
      return (field.selectionStart ?? 0) !== (field.selectionEnd ?? 0);
    } catch {
      return false; // e.g. type=number has no selection API
    }
  }
  return Boolean(window.getSelection()?.toString());
}

/** The items to show, or none: right-click on plain app chrome shows nothing. */
export function textMenuItems({ editable, hasSelection }: TextMenuTarget): TextMenuItem[] {
  if (editable) return hasSelection ? ["cut", "copy", "paste", "selectAll"] : ["paste", "selectAll"];
  return hasSelection ? ["copy"] : [];
}

export const TEXT_MENU_LABELS: Record<TextMenuItem, { label: string; keys: string }> = {
  cut: { label: "Cut", keys: "Ctrl+X" },
  copy: { label: "Copy", keys: "Ctrl+C" },
  paste: { label: "Paste", keys: "Ctrl+V" },
  selectAll: { label: "Select all", keys: "Ctrl+A" },
};
