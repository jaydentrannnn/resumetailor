import type { ReactNode } from "react";

/** Label/description and control, separated by spacing and a single row hairline. */
export function SettingRow({
  label,
  description,
  children,
}: {
  label: ReactNode;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="grid min-w-0 gap-3 border-t border-line py-4 first:border-0 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_minmax(180px,0.9fr)] sm:items-start sm:gap-6">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {description && <div className="mt-1 text-xs text-ink-muted">{description}</div>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
