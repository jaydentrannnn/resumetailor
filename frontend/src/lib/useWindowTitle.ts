import { useEffect } from "react";
import { setWindowTitle } from "../api";
import { windowTitle } from "./shell";
import { useDesktop } from "./useDesktop";

/**
 * Names the window after the page (and marks unsaved edits). The desktop window's title
 * is the shell's, which the page title does not reach, so it is set through the server.
 */
export function useWindowTitle(page: string | null, dirty: boolean): void {
  const desktop = useDesktop();
  const title = windowTitle(page, dirty);
  useEffect(() => {
    document.title = title;
    if (desktop) setWindowTitle(title).catch(() => undefined); // cosmetic
  }, [title, desktop]);
}
