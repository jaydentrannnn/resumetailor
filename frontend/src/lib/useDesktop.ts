import { useEffect, useState } from "react";
import { fetchConfig } from "../api";

/**
 * Whether the app runs inside the desktop shell (`/api/config` `desktop`), so actions
 * that only work there — native file dialogs, Show in folder, Open in Word, the app's
 * own text menu — are offered. The browser build (Docker, uvicorn) reads false.
 *
 * Fetched once per page load: the host never changes while the page is open.
 */
let cached: Promise<boolean> | null = null;
let known: boolean | null = null;

function loadDesktop(): Promise<boolean> {
  cached ??= fetchConfig()
    .then((cfg) => Boolean(cfg.desktop))
    .catch(() => false)
    .then((desktop) => (known = desktop));
  return cached;
}

export function useDesktop(): boolean {
  const [desktop, setDesktop] = useState(known ?? false);
  useEffect(() => {
    let live = true;
    void loadDesktop().then((value) => live && setDesktop(value));
    return () => {
      live = false;
    };
  }, []);
  return desktop;
}

/** Tests only: forget the cached answer. */
export function resetDesktopForTests(): void {
  cached = null;
  known = null;
}
