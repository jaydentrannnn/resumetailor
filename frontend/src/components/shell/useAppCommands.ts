import { useNavigate } from "react-router-dom";
import type { Command } from "../../lib/commands";
import { currentPrintTarget, printDocument } from "../../lib/printTarget";
import { useCommands } from "../../state/commandState";
import { type ThemePreference, useTheme } from "../../state/themeState";
import { RAIL_ITEMS } from "./railItems";

const MORE_PAGES = [
  { to: "/applications/sources", label: "Job sources", keywords: "search companies boards" },
  { to: "/vocabulary", label: "Vocabulary", keywords: "dictionary skills verbs" },
  { to: "/settings", label: "Settings", keywords: "models keys backups", key: "," },
];

const THEMES: ThemePreference[] = ["system", "light", "dark"];

/** The shell's own Ctrl+K commands: every page, the theme, printing and reloading. */
export function useAppCommands(): void {
  const navigate = useNavigate();
  const { preference, setPreference } = useTheme();
  useCommands((): Command[] => {
    const printable = currentPrintTarget();
    return [
      ...RAIL_ITEMS.map((item, i) => ({
        id: `go-${item.to}`,
        title: item.label,
        group: "Go to",
        shortcut: ["Ctrl", String(i + 1)],
        run: () => navigate(item.to),
      })),
      ...MORE_PAGES.map((page) => ({
        id: `go-${page.to}`,
        title: page.label,
        group: "Go to",
        keywords: page.keywords,
        shortcut: page.key ? ["Ctrl", page.key] : undefined,
        run: () => navigate(page.to),
      })),
      {
        id: "print",
        title: "Print the open document",
        group: "Document",
        shortcut: ["Ctrl", "P"],
        disabled: !printable,
        run: () => printable && printDocument(printable),
      },
      ...THEMES.map((theme) => ({
        id: `theme-${theme}`,
        title: `Theme: ${theme[0].toUpperCase()}${theme.slice(1)}`,
        group: "Appearance",
        keywords: "dark light mode colour color",
        disabled: theme === preference,
        run: () => setPreference(theme),
      })),
      {
        id: "reload",
        title: "Reload window",
        group: "App",
        keywords: "refresh restart",
        run: () => window.location.reload(),
      },
    ];
  });
}

/** Mounts the shell's commands; render inside `CommandProvider`. */
export function AppCommands() {
  useAppCommands();
  return null;
}
