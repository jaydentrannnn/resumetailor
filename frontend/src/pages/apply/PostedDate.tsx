import type { ApplicationRow } from "../../api";
import { localDate } from "../../lib/applicationRows";

/** When the posting went up; the date found, marked "~", when the source gave none. */
export function PostedDate({ row }: { row: ApplicationRow }) {
  const value = row.posted_at || row.discovered_at;
  if (!value) return <>—</>;
  if (row.posted_at && row.posted_known) return <>{localDate(value)}</>;
  return (
    <span className="text-ink-muted" title="Posting date unknown — date found">
      ~{localDate(value)}
    </span>
  );
}

/** How long a Needs you row has waited ("3 h ago"), with the exact time as its tooltip. */
export function WaitingSince({ at }: { at: string }) {
  const date = new Date(at);
  if (!at || Number.isNaN(date.getTime())) return <>—</>;
  const elapsed = Math.max(0, Date.now() - date.getTime());
  const minutes = Math.floor(elapsed / 60000);
  const label =
    minutes < 60
      ? `${minutes} min ago`
      : minutes < 1440
        ? `${Math.floor(minutes / 60)} h ago`
        : `${Math.floor(minutes / 1440)} d ago`;
  return (
    <time dateTime={at} title={date.toLocaleString()}>
      {label}
    </time>
  );
}
