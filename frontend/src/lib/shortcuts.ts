/** Global keyboard shortcuts: which action a keydown maps to, if any. */
/** "pages" (Ctrl+1…5, Ctrl+,) is listed for the help dialog; `railTarget` handles it. */
export type ShortcutAction = "primary" | "search" | "help" | "print" | "pages";

export const SHORTCUTS: { keys: string[]; action: ShortcutAction; description: string }[] = [
  { keys: ["Ctrl", "Enter"], action: "primary", description: "Tailor resume (on the Tailor page)" },
  {
    keys: ["Ctrl", "1…5"],
    action: "pages",
    description: "Tailor, Apply, Resume, Template, Profile",
  },
  { keys: ["Ctrl", ","], action: "pages", description: "Settings" },
  { keys: ["Ctrl", "P"], action: "print", description: "Print the open resume or letter" },
  { keys: ["/"], action: "search", description: "Search applications (on the Apply page)" },
  { keys: ["?"], action: "help", description: "Show these shortcuts" },
];

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true
  );
}

/**
 * Ctrl/Cmd+Enter works while typing (it submits the job description being typed);
 * "/" and "?" are ignored while typing so they can still be entered as text.
 * Ctrl/Cmd+P is "print" anywhere; the handler lets the browser have it when no
 * document is showing.
 */
export function shortcutFor(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "target"> &
    Partial<Pick<KeyboardEvent, "shiftKey">>,
): ShortcutAction | null {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.altKey) return "primary";
  if (e.key.toLowerCase() === "p" && (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey)
    return "print";
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return null;
  if (e.key === "/") return "search";
  if (e.key === "?") return "help";
  return null;
}
