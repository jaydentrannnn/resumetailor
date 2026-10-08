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
  return <div className={`${column} space-y-4 ${className}`.trim()}>{children}</div>;
}

/**
 * Page title: an optional mono `eyebrow`, the serif h1, a one-line lede (`description`),
 * a back link above and right-aligned `actions`.
 */
export function PageHeader({
  title,
  eyebrow,
  description,
  back,
  actions,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  description?: ReactNode;
  back?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="space-y-2.5 pb-2 sm:pt-4">
      {back}
      {eyebrow && <p className="rt-eyebrow">{eyebrow}</p>}
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <h1 className="rt-title min-w-0 text-ink">{title}</h1>
        {actions && <div className="flex flex-wrap items-center gap-3 text-sm">{actions}</div>}
      </div>
      {description && <div className="max-w-[62ch] text-[15px] text-ink-muted">{description}</div>}
    </header>
  );
}
