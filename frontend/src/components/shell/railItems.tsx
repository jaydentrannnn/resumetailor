/** The rail's pages, in Ctrl+1…5 order, with their 16px line icons. */
export type RailItem = { to: string; label: string; end?: boolean; icon: string; badge?: "apply" };

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

/** Ctrl+1…5 opens the rail's pages, Ctrl+, opens Settings. */
export function railTarget(
  e: Pick<KeyboardEvent, "key" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey">,
): string | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return null;
  if (e.key === ",") return "/settings";
  const index = Number(e.key) - 1;
  return Number.isInteger(index) && index >= 0 && index < RAIL_ITEMS.length
    ? RAIL_ITEMS[index].to
    : null;
}
