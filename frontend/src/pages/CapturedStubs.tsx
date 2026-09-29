import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listExtensionCaptures, type ApplicationRow, type CapturedItem } from "../api";
import { Card } from "../components/ui";

/** Board names as users know them (`CapturedItem.site`). */
const SITE_NAMES: Record<string, string> = { linkedin: "LinkedIn", indeed: "Indeed" };

export function siteName(site: string): string {
  return SITE_NAMES[site] ?? site;
}

/** Whether the browser extension captured this row (its "Captured" label and filter). */
export function isCaptured(row: Pick<ApplicationRow, "sources">): boolean {
  return row.sources.includes("extension");
}

/** The Applications list's "Captured" source filter: all rows, or only captured ones. */
export function filterCaptured<T extends Pick<ApplicationRow, "sources">>(
  rows: T[],
  capturedOnly: boolean,
): T[] {
  return capturedOnly ? rows.filter(isCaptured) : rows;
}

/** Small "Captured" label for a row the extension added. */
export function CapturedBadge({ row }: { row: Pick<ApplicationRow, "sources" | "capture_stub"> }) {
  if (!isCaptured(row)) return null;
  return (
    <span
      className="rounded-full border border-line px-2 py-0.5 text-micro text-ink-muted"
      title="Added from the browser extension"
    >
      {row.capture_stub ? "Captured · needs description" : "Captured"}
    </span>
  );
}

/**
 * "Needs description": jobs saved from LinkedIn/Indeed search results whose description
 * the extension has not captured yet. Opening one on the board (with the extension
 * installed) completes it; nothing in the app fetches those sites. Renders nothing when
 * there are none.
 */
export function NeedsDescriptionGroup({ refreshKey = 0 }: { refreshKey?: number }) {
  const [stubs, setStubs] = useState<CapturedItem[]>([]);
  const load = useCallback(() => {
    listExtensionCaptures(true)
      .then(setStubs)
      .catch(() => {
        /* An optional group: the rest of the page works without it. */
      });
  }, []);
  useEffect(() => {
    load();
    // Stubs complete in the browser, so re-check when the user comes back to the app.
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, [load, refreshKey]);
  if (!stubs.length) return null;
  return (
    <Card
      title={`Needs description (${stubs.length})`}
      description="Saved from search results. Open each job on the job board with the ResumeTailor extension installed and its description is saved automatically."
    >
      <ul className="divide-y divide-line">
        {stubs.map((stub) => (
          <li
            key={stub.id}
            className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <Link
                className="font-medium hover:underline"
                to={`/applications/${encodeURIComponent(stub.link_id)}`}
              >
                {stub.role}
              </Link>
              <p className="text-ink-muted">
                {[stub.company, stub.location].filter(Boolean).join(" · ")}
              </p>
            </div>
            <a
              className="rounded-md border border-line px-3 py-1.5 text-sm"
              href={stub.posting_url}
              target="_blank"
              rel="noreferrer"
            >
              Open on {siteName(stub.site)} ↗
            </a>
          </li>
        ))}
      </ul>
    </Card>
  );
}
