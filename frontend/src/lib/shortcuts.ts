/** Global keyboard shortcuts: which action a keydown maps to, if any. */
export type ShortcutAction = "primary" | "search" | "help";

export const SHORTCUTS: { keys: string[]; action: ShortcutAction; description: string }[] = [
  { keys: ["Ctrl", "Enter"], action: "primary", description: "Tailor resume (on the Tailor page)" },
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
 */
export function shortcutFor(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "target">,
): ShortcutAction | null {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.altKey) return "primary";
  if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return null;
  if (e.key === "/") return "search";
  if (e.key === "?") return "help";
  return null;
}
