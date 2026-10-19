import type { ReactNode } from "react";

/**
 * The one page column; its title is a `CommandBar`. `standard` pages (Profile,
 * Template, Vocabulary, Settings, Job sources) share a single centred column so moving
 * between them never changes the content width; `wide` pages (Tailor, Apply, an application) are dashboards that use
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
