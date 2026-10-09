import { useEffect, useId, useRef, useState } from "react";
import { useWorkspaceState } from "../state/workspaceState";
import { ProfileSwitcher } from "./workspace/ProfileSwitcher";

/** A modal (the profile manager) owns the keyboard and clicks while it is open. */
function modalOpen() {
  return !!document.querySelector('[aria-modal="true"]');
}

/**
 * The header's profile pill: a person icon and the active profile's name, opening the
 * profile switcher and profile management. Theme has its own button (`ThemeButton`);
 * everything else is on the Settings page.
 */
export function ProfileMenu() {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const { workspaces, activeId, switching } = useWorkspaceState();
  const active = workspaces.find((workspace) => workspace.id === activeId);

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
        onClick={() => setOpen((value) => !value)}
        className={`rt-header-pill rt-control inline-flex max-w-64 items-center gap-2 rounded-sm px-2 hover:text-ink ${open ? "text-ink" : "text-ink-2"}`}
        title="Profile: switch or manage profiles"
      >
        <svg
          aria-hidden
          viewBox="0 0 20 20"
          className="size-4 shrink-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <circle cx="10" cy="7" r="3.2" />
          <path d="M3.8 17.2c.9-3.2 3.3-4.9 6.2-4.9s5.3 1.7 6.2 4.9" strokeLinecap="round" />
        </svg>
        <span className="truncate">{switching ? "Switching…" : (active?.label ?? "Profile")}</span>
        <span
          aria-hidden
          className={`text-xs text-ink-muted transition-transform duration-[var(--dur-short)] ${open ? "rotate-180" : ""}`}
        >
          ▾
        </span>
      </button>
      {open && (
        <div
          id={panelId}
          role="group"
          aria-label="Profile"
          className="absolute right-0 z-40 mt-2 w-72 max-w-[calc(100vw-2rem)] space-y-2 rounded-sm border border-line bg-chrome p-4 shadow-lg"
        >
          <section className="space-y-2">
            <h2 className="rt-eyebrow">Profile</h2>
            <ProfileSwitcher />
          </section>
        </div>
      )}
    </div>
  );
}
