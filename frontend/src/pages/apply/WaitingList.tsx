import { Link } from "react-router-dom";
import { Button } from "../../components/ui";
import type { WaitingItem } from "../../api";
import { waitingLine } from "../../lib/applyPage";
import type { OperationControl } from "./OperationBanner";

/**
 * Fills that stopped on questions and wait at the back of the batch: each comes back by
 * itself once its questions are answered in the tab, or when its timer runs out. Open
 * tab goes to the form; Retry now brings it back at once; Leave it hands it to Needs you.
 */
export function WaitingList({
  items,
  now,
  onControl,
  onOpenTab,
}: {
  items: WaitingItem[];
  now: number;
  onControl: (action: OperationControl, applicationId: string) => void;
  onOpenTab?: (applicationId: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="mt-3 border-t border-line pt-3 text-[13px]">
      <h3 className="text-xs font-medium text-ink-2">Waiting on your answers</h3>
      <ul className="mt-1.5 space-y-1.5">
        {items.map((item) => (
          <li
            key={item.application_id}
            className="flex flex-wrap items-center gap-x-3 gap-y-1"
            data-testid="waiting-item"
          >
            <Link
              className="font-medium text-ink underline decoration-line-hover underline-offset-2 hover:decoration-ink"
              to={`/applications/${encodeURIComponent(item.application_id)}`}
            >
              {item.label || item.application_id}
            </Link>
            <span className="text-ink-muted">
              {item.reason ? `${item.reason} · ` : ""}
              {waitingLine(item, now)}
            </span>
            <span className="ml-auto flex flex-wrap gap-2">
              {onOpenTab && (
                <Button size="sm" onClick={() => onOpenTab(item.application_id)}>
                  Open tab
                </Button>
              )}
              <Button size="sm" onClick={() => onControl("retry_now", item.application_id)}>
                Retry now
              </Button>
              <Button
                size="sm"
                variant="plain"
                title="Stop coming back to it; it stays in Needs you"
                onClick={() => onControl("leave", item.application_id)}
              >
                Leave it
              </Button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
