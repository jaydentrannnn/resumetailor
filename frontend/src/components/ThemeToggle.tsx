import { useTheme, type ThemePreference } from "../state/themeState";

const LABELS: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/**
 * Compact header control: one click cycles System → Light → Dark.
 * Preference is stored in localStorage and overrides `prefers-color-scheme`.
 */
export function ThemeToggle() {
  const { preference, cyclePreference } = useTheme();
  const label = LABELS[preference];

  return (
    <button
      type="button"
      onClick={cyclePreference}
      className="rounded-md border border-line bg-panel px-2.5 py-1.5 text-xs font-medium text-ink-muted hover:border-accent hover:text-ink"
      title={`Theme: ${label}. Click to cycle System → Light → Dark.`}
      aria-label={`Theme ${label}. Click to change.`}
    >
      {label}
    </button>
  );
}
