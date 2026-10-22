import { useNavigate } from "react-router-dom";
import type { Command } from "../../lib/commands";
import { currentPrintTarget, printDocument } from "../../lib/printTarget";
import { useCommands } from "../../state/commandState";
import { type ThemePreference, useTheme } from "../../state/themeState";
import { useRunState } from "../../state/runState";
import { RAIL_ITEMS, visibleRailItems } from "./railItems";

const THEMES: ThemePreference[] = ["system", "light", "dark"];

/** The shell's own Ctrl+K commands: every page, the theme, printing and reloading. */
export function useAppCommands(): void {
  const navigate = useNavigate();
  const { preference, setPreference } = useTheme();
  const { settings } = useRunState();
  useCommands((): Command[] => {
    const printable = currentPrintTarget();
    const visible = visibleRailItems(settings.rail_layout);
    const visiblePaths = new Set(visible.map((i) => i.to));
    return [
      ...visible.map((item, i) => ({
        id: `go-${item.to}`,
        title: item.label,
        group: "Go to",
        shortcut: ["Ctrl", String(i + 1)],
        run: () => navigate(item.to),
      })),
      ...RAIL_ITEMS.filter((item) => !visiblePaths.has(item.to)).map((item) => ({
        id: `go-${item.to}`,
        title: item.label,
        group: "Go to",
        run: () => navigate(item.to),
      })),
      {
        id: "go-/settings",
        title: "Settings",
        group: "Go to",
        keywords: "models keys backups appearance",
        shortcut: ["Ctrl", ","],
        run: () => navigate("/settings"),
      },
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
