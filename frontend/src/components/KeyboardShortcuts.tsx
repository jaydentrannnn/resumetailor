import { useEffect, useState } from "react";
import { SHORTCUTS, shortcutFor } from "../lib/shortcuts";
import { Kbd } from "./ui/Card";
import { Modal } from "./Modal";

/**
 * Handles the global shortcuts. Pages opt in by marking elements:
 * `data-shortcut="primary"` (a button Ctrl/Cmd+Enter presses) and
 * `data-shortcut="search"` (an input "/" focuses).
 */
export function KeyboardShortcuts() {
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const action = shortcutFor(e);
      if (!action) return;
      if (action === "help") {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }
      const target = document.querySelector<HTMLElement>(`[data-shortcut="${action}"]`);
      if (!target) return;
      e.preventDefault();
      if (action === "search") target.focus();
      else if (!(target as HTMLButtonElement).disabled) target.click();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  if (!helpOpen) return null;
  return (
    <Modal title="Keyboard shortcuts" onClose={() => setHelpOpen(false)}>
      <ul className="space-y-2 text-sm">
        {SHORTCUTS.map((shortcut) => (
          <li key={shortcut.action} className="flex items-center justify-between gap-4">
            <span className="text-ink">{shortcut.description}</span>
            <span className="flex gap-1">
              {shortcut.keys.map((key) => (
                <Kbd key={key}>{key}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-muted">On a Mac, use ⌘ instead of Ctrl.</p>
    </Modal>
  );
}
