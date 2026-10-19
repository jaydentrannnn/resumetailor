import { useEffect, useState } from "react";
import {
  editableElement,
  fieldHasSelection,
  TEXT_MENU_LABELS,
  textMenuItems,
  type TextMenuItem,
} from "../lib/textMenu";
import { useDesktop } from "../lib/useDesktop";
import { Kbd } from "./ui";

type Open = { x: number; y: number; items: TextMenuItem[]; field: HTMLElement | null };

/**
 * Desktop app only: the browser's right-click menu (Back, Reload, Save as, Print,
 * Inspect) is switched off in the app window, so text gets this Cut / Copy / Paste /
 * Select all menu instead. Right-click anywhere else shows nothing. The browser build
 * keeps the browser's own menu.
 *
 * Menu items keep focus in the field (`onMouseDown` prevents the focus move), so the
 * selection they act on survives the click.
 */
export function TextContextMenu() {
  const desktop = useDesktop();
  const [open, setOpen] = useState<Open | null>(null);

  useEffect(() => {
    if (!desktop) return;
    function onContextMenu(e: MouseEvent) {
      e.preventDefault();
      const field = editableElement(e.target);
      const items = textMenuItems({
        editable: field !== null,
        hasSelection: fieldHasSelection(field),
      });
      setOpen(items.length ? { x: e.clientX, y: e.clientY, items, field } : null);
    }
    const close = () => setOpen(null);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("contextmenu", onContextMenu);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", onKey);
    window.addEventListener("blur", close);
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("contextmenu", onContextMenu);
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("blur", close);
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", close, true);
    };
  }, [desktop]);

  if (!open) return null;
  // Keep the menu on screen near the right and bottom edges.
  const left = Math.min(open.x, window.innerWidth - 216);
  const top = Math.min(open.y, window.innerHeight - open.items.length * 34 - 16);

  return (
    <div
      role="menu"
      aria-label="Text"
      style={{ left, top }}
      className="fixed z-50 w-52 rounded-sm border border-line bg-chrome p-1 shadow-lg"
      onMouseDown={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
    >
      {open.items.map((item) => (
        <button
          key={item}
          type="button"
          role="menuitem"
          className="flex w-full items-center justify-between rounded-xs px-2.5 py-1.5 text-left text-sm text-ink hover:bg-sunken"
          onClick={() => {
            void runTextCommand(item, open.field);
            setOpen(null);
          }}
        >
          {TEXT_MENU_LABELS[item].label}
          <Kbd>{TEXT_MENU_LABELS[item].keys}</Kbd>
        </button>
      ))}
    </div>
  );
}

async function runTextCommand(item: TextMenuItem, field: HTMLElement | null): Promise<void> {
  field?.focus();
  if (item === "selectAll") {
    if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) field.select();
    else document.execCommand("selectAll");
    return;
  }
  if (item === "paste") {
    // insertText keeps the field's own undo history and fires the input event React
    // listens to; the clipboard read needs the window's clipboard permission.
    try {
      const text = await navigator.clipboard.readText();
      if (text) document.execCommand("insertText", false, text);
    } catch {
      document.execCommand("paste");
    }
    return;
  }
  document.execCommand(item);
}
