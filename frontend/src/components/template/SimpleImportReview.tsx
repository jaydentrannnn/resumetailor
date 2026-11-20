import type { TemplateAnalyzeResponse } from "../../api";
import { buttonClass } from "../../lib/buttonClass";
import { readSummary } from "../../lib/readSummary";
import { StatusChip } from "../ui";
import { IssueList } from "./IssueList";

/**
 * First-run upload, after the file was read: what was found and one decision. A file
 * whose layout can be kept offers "Use this resume"; one that can't offers its words on a
 * built-in design, with the fix-your-file steps as the second choice. The analyzer's own
 * report and the mapping controls stay behind "Something's off".
 */
export function SimpleImportReview({
  fileName,
  analysis,
  ready,
  busy,
  onInstall,
  onWordsOnly,
  onAdjust,
  onAnother,
}: {
  fileName: string;
  analysis: TemplateAnalyzeResponse;
  /** The file's layout can be installed as it was read. */
  ready: boolean;
  busy: boolean;
  onInstall: () => void;
  onWordsOnly: () => void;
  onAdjust: () => void;
  onAnother: () => void;
}) {
  const blockers = analysis.issues.filter((issue) => issue.blocking);
  const warnings = analysis.issues.filter((issue) => !issue.blocking);
  const found = readSummary(analysis.sections);
  return (
    <div className="mt-4 space-y-4 border-t border-line pt-4 text-sm">
      <div>
        <p className="font-medium text-ink">
          {found.length ? `Read from ${fileName}` : `Nothing could be read from ${fileName}`}
        </p>
        <ul className="mt-2 space-y-1">
          {found.map((row) => (
            <li key={row.title} className="flex flex-wrap gap-x-3">
              <span className="text-ink">{row.title}</span>
              <span className="text-ink-muted">{row.detail}</span>
            </li>
          ))}
        </ul>
      </div>

      {ready ? (
        <>
          {warnings.length > 0 && (
            <details>
              <summary className="cursor-pointer text-ink-muted">
                {warnings.length} thing{warnings.length === 1 ? "" : "s"} worth knowing
              </summary>
              <IssueList issues={warnings} tone="warn" />
            </details>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onInstall}
              className={buttonClass("primary", "sm")}
            >
              Use this resume
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onAdjust}
              className={buttonClass("plain", "sm")}
            >
              Something's off
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onAnother}
              className={buttonClass("ghost", "sm")}
            >
              Choose a different file
            </button>
          </div>
          <p className="text-xs text-ink-muted">
            Setting up takes about 30 seconds: the app measures how much fits on your page.
          </p>
        </>
      ) : (
        <>
          <div>
            <StatusChip tone="attention">This file's design can't be kept</StatusChip>
            <p className="mt-2 text-ink-muted">
              Your jobs, projects and bullets can still be used. The app puts them on one of its
              built-in designs, which you can change at any time.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={onWordsOnly}
              className={buttonClass("primary", "sm")}
            >
              Use my words with a built-in design
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={onAnother}
              className={buttonClass("ghost", "sm")}
            >
              Choose a different file
            </button>
          </div>
          <details>
            <summary className="cursor-pointer text-ink-muted">
              Keep my own design instead: what to fix in the file
            </summary>
            <IssueList issues={blockers} tone="danger" />
            <button
              type="button"
              disabled={busy}
              onClick={onAdjust}
              className={buttonClass("plain", "sm", "mt-3")}
            >
              Show everything the app read
            </button>
          </details>
        </>
      )}
    </div>
  );
}
