import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import type { JobSettings } from "../api";
import { useRunState } from "../state/runState";

/**
 * Simple | Full view. Simple shows a new student only what they act on; a control is
 * hidden there only while it is at its default, has no problem to report and no link
 * asked for it (`?reveal=<id>`). Hidden means absent: the way back is the switch
 * (Settings › Appearance, the sidebar, Ctrl+K). Routes and commands never change.
 */
export type UiMode = NonNullable<JobSettings["ui_mode"]>;

/** Full until the server says otherwise, so a slow load never hides what someone set. */
export function isSimple(settings: Pick<JobSettings, "ui_mode">): boolean {
  return settings.ui_mode === "simple";
}

/** Whether a block is left out: only in Simple, and only when nothing asks to keep it. */
export function hiddenInSimple(simple: boolean, keep = false): boolean {
  return simple && !keep;
}

/** The ids a link asked to show (`?reveal=nightly,auto-submit`). */
export function revealedIds(search: string | URLSearchParams): Set<string> {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  return new Set(
    (params.get("reveal") ?? "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean),
  );
}

export function useUiMode(): { simple: boolean; setMode: (mode: UiMode) => void } {
  const { settings, setSettings } = useRunState();
  const setMode = useCallback(
    (mode: UiMode) => setSettings({ ...settings, ui_mode: mode }),
    [settings, setSettings],
  );
  return { simple: isSimple(settings), setMode };
}

/** True when the page was opened with `?reveal=` naming `id`. */
export function useRevealed(id: string): boolean {
  const [params] = useSearchParams();
  return revealedIds(params).has(id);
}
