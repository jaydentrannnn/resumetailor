import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useDesktop } from "../../lib/useDesktop";
import { AutomationSwitch } from "../AutomationSwitch";
import { LogoMark } from "../LogoMark";
import { ProfileMenu } from "../ProfileMenu";
import { SetupHealth } from "../SetupHealth";
import { UpdateChip } from "../UpdateChip";
import { RAIL_ITEMS, RailIcon, SETTINGS_ICON } from "./railItems";
import { useNeedsYouCount } from "./useNeedsYouCount";

// The rail is 184px wide with labels; below 900px it keeps only the icons. Class names
// stay literal (`min-[900px]:…`) so Tailwind finds them.

const rowClass = ({ isActive }: { isActive: boolean }) =>
  `relative flex items-center gap-2.5 rounded-sm px-2.5 py-[7px] text-[13px] transition-colors duration-[var(--dur-short)] ${
    isActive
      ? "bg-selected-row font-medium text-accent"
      : "text-ink-2 hover:bg-sunken hover:text-ink"
  }`;

/**
 * The app's left rail: the five work areas, then background state (nightly apply,
 * setup, update), the profile switcher and Settings at the bottom. Shortcut hints show
 * only in the desktop app, where the browser does not keep Ctrl+1…5 for its tabs.
 */
export function AppRail() {
  const desktop = useDesktop();
  const needsYou = useNeedsYouCount();
  return (
    <nav
      aria-label="Main"
      className="sticky top-0 z-40 flex h-screen w-[52px] shrink-0 flex-col gap-0.5 border-r border-line bg-panel px-1.5 py-3 min-[900px]:w-[184px] min-[900px]:px-2"
    >
      <p className="mb-3 flex items-center gap-2.5 px-2.5 font-display text-[15px] font-semibold tracking-tight text-ink">
        <LogoMark className="h-4 w-3.5" />
        <span className="hidden min-[900px]:inline">ResumeTailor</span>
      </p>
      {RAIL_ITEMS.map((item, i) => (
        <NavLink key={item.to} to={item.to} end={item.end} className={rowClass} title={item.label}>
          <RailIcon path={item.icon} />
          <span className="hidden flex-1 min-[900px]:inline">{item.label}</span>
          {item.badge === "apply" && needsYou ? (
            <span
              className="absolute left-6 top-0.5 rounded-full bg-attn px-1 text-[10px] font-medium text-on-accent min-[900px]:static min-[900px]:px-1.5 min-[900px]:text-[11px]"
              aria-label={`${needsYou} need you`}
            >
              {needsYou}
            </span>
          ) : null}
          {desktop && (
            <span className="hidden font-mono text-[11px] text-ink-muted min-[900px]:inline">
              Ctrl {i + 1}
            </span>
          )}
        </NavLink>
      ))}
      <div className="min-h-6 flex-1" />
      <RailStatus />
      <NavLink to="/settings" className={rowClass} title="Settings">
        <RailIcon path={SETTINGS_ICON} />
        <span className="hidden flex-1 min-[900px]:inline">Settings</span>
        {desktop && (
          <span className="hidden font-mono text-[11px] text-ink-muted min-[900px]:inline">
            Ctrl ,
          </span>
        )}
      </NavLink>
    </nav>
  );
}

/** Background state and the profile switcher; behind one button while the rail is narrow. */
function RailStatus() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const group = (
    <div className="flex flex-col items-stretch gap-1.5 [&>*]:w-full [&_.rt-header-pill]:w-full [&_.rt-header-pill]:justify-start">
      <AutomationSwitch />
      <SetupHealth />
      <UpdateChip />
      <ProfileMenu />
    </div>
  );
  return (
    <div ref={ref} className="relative mb-1 border-t border-line pt-2">
      <div className="hidden min-[900px]:block">{group}</div>
      <button
        type="button"
        aria-label="Status and profile"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full justify-center rounded-sm py-[7px] text-ink-2 hover:bg-sunken hover:text-ink min-[900px]:hidden"
      >
        <RailIcon path="M3 8h.01M8 8h.01M13 8h.01" />
      </button>
      {open && (
        <div className="absolute bottom-0 left-full z-40 ml-2 w-56 rounded-sm border border-line bg-chrome p-2 shadow-lg min-[900px]:hidden">
          {group}
        </div>
      )}
    </div>
  );
}
