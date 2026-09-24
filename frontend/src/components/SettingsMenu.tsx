import { useEffect, useId, useRef, useState } from "react";
import { useTheme, type ThemePreference } from "../state/themeState";
import { useWorkspaceState } from "../state/workspaceState";
import { ProfileSwitcher } from "./workspace/ProfileSwitcher";

const THEMES: Array<[ThemePreference, string]> = [["system", "System"], ["light", "Light"], ["dark", "Dark"]];

/** A modal (the profile manager) owns the keyboard and clicks while it is open. */
function modalOpen() {
  return !!document.querySelector('[aria-modal="true"]');
}

/**
 * The header's one settings control: a gear button (named after the active profile)
 * that opens the profile switcher, profile management, and the theme choice.
 */
export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const { workspaces, activeId, switching } = useWorkspaceState();
  const { preference, setPreference } = useTheme();
  const active = workspaces.find(workspace => workspace.id === activeId);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (modalOpen() || rootRef.current?.contains(event.target as Node)) return;
      setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || modalOpen()) return;
      setOpen(false);
      buttonRef.current?.focus();
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="true"
        onClick={() => setOpen(value => !value)}
        className="inline-flex min-h-9 max-w-64 items-center gap-2 rounded-md border border-line bg-panel px-3 py-1.5 text-sm font-medium text-ink hover:border-accent"
        title="Settings: profile and theme"
      >
        <svg aria-hidden viewBox="0 0 20 20" className="size-4 shrink-0 text-ink-muted" fill="none" stroke="currentColor" strokeWidth="1.6">
          <circle cx="10" cy="10" r="2.6" />
          <path d="M10 1.8v2.4M10 15.8v2.4M1.8 10h2.4M15.8 10h2.4M4.2 4.2l1.7 1.7M14.1 14.1l1.7 1.7M4.2 15.8l1.7-1.7M14.1 5.9l1.7-1.7" strokeLinecap="round" />
        </svg>
        <span className="truncate">{switching ? "Switching…" : active?.label ?? "Settings"}</span>
        <span aria-hidden className="text-xs text-ink-muted">▾</span>
      </button>
      {open && (
        <div id={panelId} role="group" aria-label="Settings" className="absolute right-0 z-40 mt-2 w-72 max-w-[calc(100vw-2rem)] space-y-4 rounded-lg border border-line bg-panel p-4 shadow-lg">
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Profile</h2>
            <ProfileSwitcher stacked />
          </section>
          <section className="space-y-2 border-t border-line pt-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">Theme</h2>
            <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-md border border-line p-1">
              {THEMES.map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={preference === value}
                  onClick={() => setPreference(value)}
                  className={`min-h-9 rounded px-2 text-sm ${preference === value ? "bg-accent text-on-accent" : "text-ink-muted hover:text-ink"}`}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
