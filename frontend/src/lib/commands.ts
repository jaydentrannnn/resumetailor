/**
 * The Ctrl+K command list: what can be run from anywhere, and how a typed query picks
 * from it. Pages add their own commands with `useCommands` (`state/commandState.tsx`);
 * the shell adds navigation, theme and window commands.
 */
export type Command = {
  id: string;
  title: string;
  /** Heading the command is listed under; see `GROUP_ORDER`. */
  group: string;
  /** Other words it answers to ("download" for Save). */
  keywords?: string;
  /** Keys shown beside it, e.g. ["Ctrl", "S"]. */
  shortcut?: string[];
  /** Left out of the list (the page cannot do it right now). */
  disabled?: boolean;
  run: () => void;
};

/** This page's commands first, then getting around, then the app itself. */
export const GROUP_ORDER = [
  "Tailor",
  "Document",
  "Resume",
  "Profile",
  "Apply",
  "Go to",
  "Appearance",
  "App",
];

function groupRank(group: string): number {
  const index = GROUP_ORDER.indexOf(group);
  return index < 0 ? GROUP_ORDER.length : index;
}

/** 0: the title starts with the query; 1: a title word does; 2: it matches elsewhere. */
function matchRank(command: Command, words: string[]): number | null {
  const title = command.title.toLowerCase();
  const haystack = `${title} ${command.group} ${command.keywords ?? ""}`.toLowerCase();
  if (!words.every((word) => haystack.includes(word))) return null;
  if (!words.length || title.startsWith(words.join(" "))) return 0;
  return title.split(/\s+/).some((part) => part.startsWith(words[0])) ? 1 : 2;
}

/**
 * The commands a query shows, best first: every query word must appear in the title,
 * group or keywords. Ties keep group order, then the order commands were added. A
 * repeated id keeps its first copy.
 */
export function matchCommands(commands: Command[], query: string): Command[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const seen = new Set<string>();
  return commands
    .map((command, index) => ({ command, index, rank: matchRank(command, words) }))
    .filter(({ command, rank }) => {
      if (command.disabled || rank === null || seen.has(command.id)) return false;
      seen.add(command.id);
      return true;
    })
    .sort(
      (a, b) =>
        (words.length ? a.rank! - b.rank! : 0) ||
        groupRank(a.command.group) - groupRank(b.command.group) ||
        a.index - b.index,
    )
    .map(({ command }) => command);
}
