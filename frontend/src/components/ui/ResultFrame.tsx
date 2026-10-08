import type { ReactNode } from "react";
import { Tile } from "./Tile";

/**
 * The frame of a result card (report, documents, skills, experience, bullet review).
 * Standalone (the application page) it is its own `Tile`; `embedded` inside another tile
 * (the Tailor page's "Last result", the application page's bullet editor) it drops the
 * box and steps the heading down to h3, so there is never a box inside a box.
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
  return (
    <Tile
      as={embedded ? "div" : "section"}
      embedded={embedded}
      title={title}
      description={description}
      actions={actions}
      className={className}
    >
      {children}
    </Tile>
  );
}
