import type { ReactNode } from "react";

/**
 * The one page shell. `standard` pages (Profile, Template, Vocabulary, Settings, Job
 * sources) share a single centred column so moving between them never changes the
 * content width; `wide` pages (Tailor, Apply, an application) are dashboards that use
 * the full main area.
 */
export function Page({
  width = "standard",
  className = "",
  children,
}: {
  width?: "standard" | "wide";
  className?: string;
  children: ReactNode;
}) {
  const column = width === "standard" ? "mx-auto w-full max-w-6xl" : "";
  return <div className={`${column} space-y-6 ${className}`.trim()}>{children}</div>;
}

/** Page title with an optional back link, description and right-aligned actions. */
export function PageHeader({
  title,
  description,
  back,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  back?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="space-y-2">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-[28px] font-semibold text-ink">{title}</h1>
          {description && <div className="mt-1 text-sm text-ink-muted">{description}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-3 text-sm">{actions}</div>}
      </div>
    </header>
  );
}
