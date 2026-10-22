import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { saveAppearance, saveTheme } from "../api";
import logoMarkBlack from "../assets/logo-mark-black.svg";
import logoMarkWhite from "../assets/logo-mark-white.svg";

declare global {
  interface Window {
    __RT_DESKTOP_THEME__?: ThemePreference | null;
    __RT_DESKTOP_ACCENT__?: string | null;
  }
}

/** Persisted preference: follow OS, or force light/dark. */
export type ThemePreference = "system" | "light" | "dark";

/** Resolved appearance actually painted on `<html>`. */
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "resume-tailor-theme";
const ACCENT_KEY = "resume-tailor-accent";
const HEX = /^#[0-9a-fA-F]{6}$/;

type ThemeContextValue = {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (next: ThemePreference) => void;
  /** Cycle system → light → dark → system. */
  cyclePreference: () => void;
  /** Custom accent hex, or null for the default green. */
  accent: string | null;
  setAccent: (next: string | null) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * Read a stored theme preference, defaulting to system when missing or invalid.
 */
function readStoredPreference(): ThemePreference {
  const desktop = window.__RT_DESKTOP_THEME__;
  if (desktop === "light" || desktop === "dark" || desktop === "system") return desktop;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "light" || raw === "dark" || raw === "system") return raw;
  } catch {
    /* private mode / blocked storage — fall through */
  }
  return "system";
}

/**
 * Read a stored accent hex, or null for the default green.
 */
function readStoredAccent(): string | null {
  const desktop = window.__RT_DESKTOP_ACCENT__;
  if (typeof desktop === "string" && HEX.test(desktop)) return desktop;
  if (desktop === null) return null;
  try {
    const raw = localStorage.getItem(ACCENT_KEY);
    if (raw === "" || raw === "null") return null;
    if (raw && HEX.test(raw)) return raw;
  } catch {
    /* blocked storage */
  }
  return null;
}

/**
 * Map preference + current OS scheme to the concrete light/dark tokens to apply.
 */
export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference === "light" || preference === "dark") return preference;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Write `data-theme` (and native `color-scheme`) so CSS tokens and form controls match.
 */
function applyResolved(resolved: ResolvedTheme): void {
  document.documentElement.setAttribute("data-theme", resolved);
  document.documentElement.style.colorScheme = resolved;
  const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (icon) icon.href = resolved === "dark" ? logoMarkWhite : logoMarkBlack;
}

/**
 * Apply or clear a custom accent on `<html>` (`data-accent` + `--rt-accent-base`).
 */
export function applyAccent(accent: string | null): void {
  const root = document.documentElement;
  if (accent && HEX.test(accent)) {
    root.setAttribute("data-accent", "");
    root.style.setProperty("--rt-accent-base", accent);
  } else {
    root.removeAttribute("data-accent");
    root.style.removeProperty("--rt-accent-base");
  }
}

/**
 * Theme preference lives on `<html>` via `data-theme`, persisted in localStorage.
 * Mount above the router so the header toggle works on every page.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const themeWrite = useRef<Promise<unknown>>(Promise.resolve());
  const accentWrite = useRef<Promise<unknown>>(Promise.resolve());
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [accent, setAccentState] = useState<string | null>(readStoredAccent);
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    resolveTheme(readStoredPreference()),
  );

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore quota / private mode */
    }
    const nextResolved = resolveTheme(next);
    setResolved(nextResolved);
    applyResolved(nextResolved);
  }, []);

  const setAccent = useCallback((next: string | null) => {
    const value = next && HEX.test(next) ? next : null;
    setAccentState(value);
    try {
      if (value) localStorage.setItem(ACCENT_KEY, value);
      else localStorage.removeItem(ACCENT_KEY);
    } catch {
      /* blocked storage */
    }
    applyAccent(value);
    if (window.__RT_DESKTOP_THEME__ !== undefined) {
      window.__RT_DESKTOP_ACCENT__ = value;
      accentWrite.current = accentWrite.current
        .catch(() => undefined)
        .then(() => saveAppearance({ accent: value }));
      void accentWrite.current.catch(() => undefined);
    }
  }, []);

  const cyclePreference = useCallback(() => {
    const order: ThemePreference[] = ["system", "light", "dark"];
    const idx = order.indexOf(preference);
    setPreference(order[(idx + 1) % order.length]!);
  }, [preference, setPreference]);

  // Keep `data-theme` in sync on mount and when OS scheme changes under "system".
  useEffect(() => {
    // Serialize desktop writes so a quick sequence of theme changes saves the last.
    if (window.__RT_DESKTOP_THEME__ !== undefined) {
      window.__RT_DESKTOP_THEME__ = preference;
      themeWrite.current = themeWrite.current
        .catch(() => undefined)
        .then(() => saveTheme(preference));
      void themeWrite.current.catch(() => undefined);
    }
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      /* blocked storage */
    }
    applyResolved(resolveTheme(preference));
    setResolved(resolveTheme(preference));
    if (preference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      const next = resolveTheme("system");
      setResolved(next);
      applyResolved(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  useEffect(() => {
    applyAccent(accent);
  }, [accent]);

  const value = useMemo(
    () => ({ preference, resolved, setPreference, cyclePreference, accent, setAccent }),
    [preference, resolved, setPreference, cyclePreference, accent, setAccent],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/**
 * Access theme preference / resolved mode. Must be under `ThemeProvider`.
 */
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
