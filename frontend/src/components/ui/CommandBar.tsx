import { type ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";
import { useShell } from "../../lib/shell";

/**
 * The page's bar at the top of the work area: the title, a short `state` line (what
 * is selected or saved), and the page's actions on the right. It renders into the
 * shell's slot so it spans the work area whatever width the page column has, and it
 * names the window (`windowTitle`, else a string `title`).
 */
export function CommandBar({
  title,
  back,
  state,
  actions,
  windowTitle,
}: {
  title: ReactNode;
  back?: ReactNode;
  state?: ReactNode;
  actions?: ReactNode;
  windowTitle?: string;
}) {
  const shell = useShell();
  const name = windowTitle ?? (typeof title === "string" ? title : null);
  const setPageTitle = shell?.setPageTitle;
  useEffect(() => {
    if (!setPageTitle) return;
    setPageTitle(name);
    return () => setPageTitle(null);
  }, [setPageTitle, name]);

  const bar = (
    <div className="flex min-h-12 flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-paper px-4 py-1.5 sm:px-6">
      {back && <div className="text-[13px] text-ink-muted">{back}</div>}
      <h1 className="min-w-0 truncate font-display text-lg font-medium tracking-[-0.01em] text-ink">
        {title}
      </h1>
      {state && (
        <>
          <span aria-hidden className="text-line-hover">
            |
          </span>
          <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
            {state}
          </div>
        </>
      )}
      <div className="flex-1" />
      {actions && <div className="flex flex-wrap items-center gap-2 text-sm">{actions}</div>}
    </div>
  );
  return shell?.commandBar ? createPortal(bar, shell.commandBar) : bar;
}
