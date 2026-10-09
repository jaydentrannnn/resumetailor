import { useTheme, type ThemePreference } from "../state/themeState";

const ORDER: ThemePreference[] = ["system", "light", "dark"];
const NAMES: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/** Monitor, sun or moon: whichever mode is chosen now. */
function ThemeIcon({ preference }: { preference: ThemePreference }) {
  const common = {
    "aria-hidden": true,
    viewBox: "0 0 20 20",
    className: "size-4",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (preference === "light")
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="3.4" />
        <path d="M10 2.2v1.6M10 16.2v1.6M2.2 10h1.6M16.2 10h1.6M4.5 4.5l1.1 1.1M14.4 14.4l1.1 1.1M4.5 15.5l1.1-1.1M14.4 5.6l1.1-1.1" />
      </svg>
    );
  if (preference === "dark")
    return (
      <svg {...common}>
        <path d="M16.5 12.2A6.8 6.8 0 0 1 7.8 3.5a6.8 6.8 0 1 0 8.7 8.7Z" />
      </svg>
    );
  return (
    <svg {...common}>
      <rect x="2.5" y="3.5" width="15" height="10" rx="1.2" />
      <path d="M7 17h6M10 13.5V17" />
    </svg>
  );
}

/** The header's theme switch: one click moves System → Light → Dark → System. */
export function ThemeButton() {
  const { preference, setPreference } = useTheme();
  const next = ORDER[(ORDER.indexOf(preference) + 1) % ORDER.length];
  const label = `Theme: ${NAMES[preference]}. Switch to ${NAMES[next]}`;
  return (
    <button
      type="button"
      onClick={() => setPreference(next)}
      aria-label={label}
      title={label}
      className="rt-header-pill rt-control inline-flex items-center justify-center rounded-sm px-2 text-ink-2 hover:text-ink"
    >
      <ThemeIcon preference={preference} />
    </button>
  );
}
