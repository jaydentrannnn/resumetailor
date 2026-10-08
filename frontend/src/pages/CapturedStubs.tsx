import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listExtensionCaptures, type ApplicationRow, type CapturedItem } from "../api";
import { buttonClass, StatusChip } from "../components/ui";

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
    <span title="Added from the browser extension">
      <StatusChip tone={row.capture_stub ? "attention" : "muted"}>
        {row.capture_stub ? "Captured · needs description" : "Captured"}
      </StatusChip>
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
    <section className="mb-4 border-b border-line pb-4">
      <h3 className="text-[13px] font-semibold text-ink">{`Needs description (${stubs.length})`}</h3>
      <p className="mt-1 text-xs text-ink-muted">
        Saved from search results. Open each job on the job board with the ResumeTailor extension
        installed and its description is saved automatically.
      </p>
      <ul className="mt-2 divide-y divide-line">
        {stubs.map((stub) => (
          <li
            key={stub.id}
            className="flex flex-wrap items-center justify-between gap-3 py-2 text-sm"
          >
            <div className="min-w-0">
              <Link
                className="font-medium text-ink underline-offset-2 hover:underline"
                to={`/applications/${encodeURIComponent(stub.link_id)}`}
              >
                {stub.role}
              </Link>
              <p className="text-ink-muted">
                {[stub.company, stub.location].filter(Boolean).join(" · ")}
              </p>
            </div>
            <a
              className={buttonClass("secondary", "sm")}
              href={stub.posting_url}
              target="_blank"
              rel="noreferrer"
            >
              Open on {siteName(stub.site)} ↗
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
