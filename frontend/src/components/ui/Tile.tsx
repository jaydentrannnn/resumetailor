import type { ElementType, ReactNode } from "react";

const PADDING = { md: "p-5 sm:px-6", sm: "p-4", none: "" };

/**
 * A tile: the soft grey surface with a hairline border and 4px corners. Inside a tile use
 * spacing or a single hairline (`TileSection`), never nested boxes. `title` renders an h2
 * (`rt-tile-title`), `eyebrow` a mono label above it, `meta` quiet text beside it and
 * `actions` sit on the right.
 */
export function Tile({
  title,
  eyebrow,
  meta,
  description,
  actions,
  as: Tag = "section",
  padding = "md",
  children,
  className = "",
  ...rest
}: {
  title?: ReactNode;
  eyebrow?: ReactNode;
  meta?: ReactNode;
  /** Longer supporting line under the title (kept from `Card`). */
  description?: ReactNode;
  actions?: ReactNode;
  as?: ElementType;
  padding?: keyof typeof PADDING;
  children?: ReactNode;
  className?: string;
} & Partial<Record<`aria-${string}` | `data-${string}` | "id", string>>) {
  const heading = title || eyebrow || meta || actions || description;
  return (
    <Tag
      className={`min-w-0 rounded-sm border border-line bg-panel ${PADDING[padding]} ${className}`.trim()}
      {...rest}
    >
      {heading && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            {eyebrow && <p className="rt-eyebrow mb-1">{eyebrow}</p>}
            {(title || meta) && (
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                {title && <h2 className="rt-tile-title">{title}</h2>}
                {meta && <span className="text-xs text-ink-muted">{meta}</span>}
              </div>
            )}
            {description && <p className="mt-1 text-sm text-ink-muted">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  );
}

/** A sub-section inside a tile, separated from the one above by a single hairline. */
export function TileSection({
  title,
  actions,
  children,
  className = "",
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`border-t border-line pt-4 first:border-t-0 first:pt-0 ${className}`.trim()}>
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-[13px] font-semibold text-ink">{title}</h3>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}

/** Legacy name for `Tile`; same props. */
export const Card = Tile;

/** What a list or page shows when it has nothing yet, with the next step as a button. */
export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      {icon && (
        <div aria-hidden="true" className="text-2xl text-ink-muted">
          {icon}
        </div>
      )}
      <p className="font-display text-2xl font-[350] leading-tight text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** Placeholder block while content loads. */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={`block animate-pulse rounded-xs bg-sunken motion-reduce:animate-none ${className}`}
    />
  );
}

/** A keyboard key, e.g. <Kbd>Ctrl</Kbd>. */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-xs border border-line-hover bg-field px-1.5 py-0.5 font-mono text-micro text-ink">
      {children}
    </kbd>
  );
}
