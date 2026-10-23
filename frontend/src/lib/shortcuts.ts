/** Global keyboard shortcuts: which action a keydown maps to, if any. */
/**
 * "pages" (Ctrl+1…6, Ctrl+,) and "undo" are listed for the help dialog; `railTarget` and
 * the Resume editor (`undoKeyFor`) handle them.
 */
export type ShortcutAction =
  "commands" | "primary" | "save" | "find" | "search" | "help" | "print" | "pages" | "undo";

export const SHORTCUTS: { keys: string[]; action: ShortcutAction; description: string }[] = [
  { keys: ["Ctrl", "K"], action: "commands", description: "Find a page or an action" },
  { keys: ["Ctrl", "Enter"], action: "primary", description: "Tailor resume (on the Tailor page)" },
  {
    keys: ["Ctrl", "1…6"],
    action: "pages",
    description: "Tailor, Apply, Resume, Template, Profile, Tracker",
  },
  { keys: ["Ctrl", ","], action: "pages", description: "Settings" },
  { keys: ["Ctrl", "S"], action: "save", description: "Save (Resume and Profile)" },
  { keys: ["Ctrl", "Z"], action: "undo", description: "Undo a removed or moved item (Resume)" },
  { keys: ["Ctrl", "Shift", "Z"], action: "undo", description: "Redo (Resume)" },
  { keys: ["Ctrl", "P"], action: "print", description: "Print the open resume or letter" },
  { keys: ["Ctrl", "F"], action: "find", description: "Find on this page (desktop app)" },
  { keys: ["/"], action: "search", description: "Search applications or resume entries" },
  { keys: ["?"], action: "help", description: "Show these shortcuts" },
];

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true
  );
}

type KeyInput = Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "target"> &
  Partial<Pick<KeyboardEvent, "shiftKey">>;

/** Ctrl/Cmd plus `letter`, without Alt or Shift. */
function command(e: KeyInput, letter: string): boolean {
  return e.key.toLowerCase() === letter && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey;
}

/**
 * Ctrl/Cmd+Enter works while typing (it submits the job description being typed);
 * "/" and "?" are ignored while typing so they can still be entered as text.
 * Ctrl/Cmd+K, P, S and F work anywhere; the handler lets the browser have them when the
 * page has nothing to print, save or find.
 */
export function shortcutFor(e: KeyInput): ShortcutAction | null {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.altKey) return "primary";
  if (command(e, "k")) return "commands";
  if (command(e, "p")) return "print";
  if (command(e, "s")) return "save";
  if (command(e, "f")) return "find";
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return null;
  if (e.key === "/") return "search";
  if (e.key === "?") return "help";
  return null;
}

/**
 * Ctrl/Cmd+Z undoes and Ctrl/Cmd+Shift+Z or Ctrl+Y redoes, outside text fields only:
 * inside one, the field's own text undo applies.
 */
export function undoKeyFor(e: KeyInput): "undo" | "redo" | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || isTyping(e.target)) return null;
  const key = e.key.toLowerCase();
  if (key === "z") return e.shiftKey ? "redo" : "undo";
  if (key === "y" && !e.shiftKey) return "redo";
  return null;
}
