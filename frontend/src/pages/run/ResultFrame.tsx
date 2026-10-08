import type { ReactNode } from "react";
import { Tile } from "../../components/ui";

/**
 * The frame of a result card (report, documents, skills, experience, bullet review).
 * Standalone (the application page) it is its own `Tile`; `embedded` inside the Tailor
 * page's "Last result" tile it drops the box and steps the heading down to h3, so there
 * is never a box inside a box.
 */
export function ResultFrame({
  embedded = false,
  title,
  description,
  actions,
  children,
  className = "",
}: {
  embedded?: boolean;
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  if (!embedded) {
    return (
      <Tile title={title} description={description} actions={actions} className={className}>
        {children}
      </Tile>
    );
  }
  const heading = title || description || actions;
  return (
    <div className={`min-w-0 ${className}`.trim()}>
      {heading && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {title && <h3 className="rt-tile-title">{title}</h3>}
            {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
