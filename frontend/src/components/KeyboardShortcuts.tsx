import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { currentPrintTarget, printDocument } from "../lib/printTarget";
import { SHORTCUTS, shortcutFor } from "../lib/shortcuts";
import { useDesktop } from "../lib/useDesktop";
import { useCommands } from "../state/commandState";
import { useRunState } from "../state/runState";
import { railTarget, visibleRailItems } from "./shell/railItems";
import { Kbd } from "./ui/Tile";
import { Modal } from "./Modal";

/**
 * Handles the global shortcuts. Pages opt in by marking elements:
 * `data-shortcut="primary"` (a button Ctrl/Cmd+Enter presses),
 * `data-shortcut="save"` (a button Ctrl/Cmd+S presses) and
 * `data-shortcut="search"` (an input "/" focuses, and Ctrl/Cmd+F in the desktop app;
 * the browser keeps its own find). Viewers register what Ctrl+P prints with
 * `usePrintTarget`.
 */
export function KeyboardShortcuts() {
  const [helpOpen, setHelpOpen] = useState(false);
  const navigate = useNavigate();
  const desktop = useDesktop();
  const { settings } = useRunState();
  const railItems = visibleRailItems(settings.rail_layout);
  useCommands(() => [
    {
      id: "app-shortcuts",
      title: "Keyboard shortcuts",
      group: "App",
      keywords: "help keys",
      shortcut: ["?"],
      run: () => setHelpOpen(true),
    },
  ]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const page = railTarget(e, railItems);
      if (page) {
        e.preventDefault();
        navigate(page);
        return;
      }
      const action = shortcutFor(e);
      if (!action || action === "commands") return; // CommandPalette's
      if (action === "help") {
        e.preventDefault();
        setHelpOpen(true);
        return;
      }
      if (action === "print") {
        const url = currentPrintTarget();
        if (!url) return;
        e.preventDefault();
        printDocument(url);
        return;
      }
      if (action === "find" && !desktop) return;
      const marker = action === "find" ? "search" : action;
      const target = document.querySelector<HTMLElement>(`[data-shortcut="${marker}"]`);
      if (!target) return;
      e.preventDefault();
      if (action === "save") {
        // Fields that commit on blur must commit before Save reads the draft.
        const active =
          document.activeElement instanceof HTMLElement ? document.activeElement : null;
        active?.blur();
        window.setTimeout(() => {
          if (!(target as HTMLButtonElement).disabled) target.click();
          active?.focus();
        }, 0);
      } else if (target instanceof HTMLInputElement) {
        target.focus();
        if (action === "find") target.select();
      } else if (!(target as HTMLButtonElement).disabled) target.click();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [navigate, desktop, railItems]);
  if (!helpOpen) return null;
  return (
    <Modal title="Keyboard shortcuts" onClose={() => setHelpOpen(false)}>
      <ul className="space-y-2 text-sm">
        {SHORTCUTS.map((shortcut) => (
          <li key={shortcut.description} className="flex items-center justify-between gap-4">
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
