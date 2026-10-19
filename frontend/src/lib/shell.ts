import { createContext, useContext } from "react";

/**
 * What the app shell lends its pages: the command-bar slot at the top of the work area
 * (`ui/CommandBar` renders there) and the page's name for the window title.
 */
export type ShellSlots = {
  commandBar: HTMLElement | null;
  setPageTitle: (title: string | null) => void;
};

export const ShellContext = createContext<ShellSlots | null>(null);

/** Null outside the shell (tests, isolated renders): the bar renders in place. */
export function useShell(): ShellSlots | null {
  return useContext(ShellContext);
}

/** "Acme · Engineer — ResumeTailor", with "• " in front while edits are unsaved. */
export function windowTitle(page: string | null, dirty: boolean): string {
  const base = page ? `${page} — ResumeTailor` : "ResumeTailor";
  return dirty ? `• ${base}` : base;
}
