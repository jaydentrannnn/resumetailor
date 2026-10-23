/** The rail's pages, with their 16px line icons. Settings is separate and never hideable. */

export type RailItem = {
  to: string;
  label: string;
  end?: boolean;
  icon: string;
  badge?: "apply" | "email";
  /** When true, hidden until the user pins it in Appearance › Sidebar. */
  optional?: boolean;
};

export type RailLayout = { order: string[]; hidden: string[] };

/** Shipped pages in Ctrl+1…6 order; optional pages are off until pinned. */
export const RAIL_ITEMS: RailItem[] = [
  { to: "/", label: "Tailor", end: true, icon: "M3 2h7l3 3v9H3zM6 8h4M6 11h4" },
  { to: "/applications", label: "Apply", icon: "M2 4h12v9H2zM6 4V2.5h4V4", badge: "apply" },
  { to: "/resume", label: "Resume", icon: "M3 3h10M3 6.5h10M3 10h6M3 13.5h8" },
  { to: "/template", label: "Template", icon: "M2.5 2h11v12h-11zM2.5 6h11M6.5 6v8" },
  {
    to: "/profile",
    label: "Profile",
    icon: "M5.5 5.5a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M3 14c.6-2.8 2.6-4 5-4s4.4 1.2 5 4",
  },
  // After the first five so their Ctrl+1…5 shortcuts stay where they were (Tracker is Ctrl+6).
  { to: "/tracker", label: "Tracker", icon: "M2 2.5h3.5v11H2zM6.25 2.5h3.5v7h-3.5zM10.5 2.5H14v9h-3.5z", badge: "email" },
  {
    to: "/vocabulary",
    label: "Vocabulary",
    icon: "M3 3h10v10H3zM5 6h6M5 9h4",
    optional: true,
  },
  {
    to: "/applications/sources",
    label: "Job sources",
    icon: "M2 4h12M4 4v9M12 4v9M6 8h4",
    optional: true,
  },
];

export const SETTINGS_ICON =
  "M8 5.8a2.2 2.2 0 1 0 0 4.4a2.2 2.2 0 1 0 0-4.4M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4";

/** Monitor, sun and moon for the theme row: whichever mode is chosen now. */
export const THEME_ICONS = {
  system: "M2 3h12v8H2zM5.5 14h5M8 11v3",
  light:
    "M8 5.3a2.7 2.7 0 1 0 0 5.4a2.7 2.7 0 1 0 0-5.4M8 1.5v1.3M8 13.2v1.3M1.5 8h1.3M13.2 8h1.3M3.4 3.4l.9.9M11.7 11.7l.9.9M3.4 12.6l.9-.9M11.7 4.3l.9-.9",
  dark: "M13.2 9.8A5.4 5.4 0 0 1 6.2 2.8a5.4 5.4 0 1 0 7 7Z",
} as const;

export function RailIcon({ path }: { path: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="size-4 shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={path} />
    </svg>
  );
}

/**
 * Pages shown in the rail, in the saved order. Optional pages stay hidden until listed
 * in `order` and not in `hidden`. At least one page always remains.
 */
export function visibleRailItems(layout?: RailLayout | null): RailItem[] {
  const byPath = new Map(RAIL_ITEMS.map((item) => [item.to, item]));
  const hidden = new Set(layout?.hidden ?? []);
  const ordered = (
    layout?.order?.length ? layout.order : RAIL_ITEMS.filter((i) => !i.optional).map((i) => i.to)
  )
    .map((to) => byPath.get(to))
    .filter((item): item is RailItem => !!item && !hidden.has(item.to));
  // Optional pages not named in order stay out; required pages missing from a bad
  // saved order are appended so the rail never empties.
  const seen = new Set(ordered.map((i) => i.to));
  for (const item of RAIL_ITEMS) {
    if (item.optional || seen.has(item.to) || hidden.has(item.to)) continue;
    ordered.push(item);
    seen.add(item.to);
  }
  if (ordered.length === 0) {
    return RAIL_ITEMS.filter((i) => !i.optional);
  }
  return ordered;
}

/** Ctrl+1…n opens the visible rail pages, Ctrl+, opens Settings. */
export function railTarget(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">,
  items: RailItem[] = visibleRailItems(),
): string | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return null;
  if (e.key === ",") return "/settings";
  const index = Number(e.key) - 1;
  return Number.isInteger(index) && index >= 0 && index < items.length ? items[index].to : null;
}
