import {
  applicationsExportUrl,
  type ApplicationRow,
  type ApplySettings,
  type SourcesStatus,
} from "../../api";
import { Button, buttonClass, Switch } from "../../components/ui";
import { canFillAfterReview } from "../../lib/applicationRows";
import { canRetailor, fillBlockers, TERMINAL_STATUSES } from "../../lib/applyPage";
import { GLOSSARY } from "../../lib/glossary";
import { sourcesHeadline } from "../../lib/sources";
import { AgeWindowPicker } from "./AgeWindowPicker";

/** The one-search-only options of the next Find jobs; none of them is saved. */
export interface FindOptions {
  limit: string;
  dryRun: boolean;
  /** null follows the saved setting; a number widens or narrows the next Find only. */
  ageDays: number | null;
}

/** In progress tab, filter row: Find jobs, its one-off Search options, and Export CSV. */
export function FindJobsTools({
  apply,
  options,
  onOptions,
  busy,
  active,
  anySource,
  onFind,
}: {
  apply: ApplySettings;
  options: FindOptions;
  onOptions: (next: FindOptions) => void;
  busy: boolean;
  active: boolean;
  anySource: boolean;
  onFind: () => void;
}) {
  const { limit, dryRun, ageDays } = options;
  return (
    <>
      <details className="relative">
        <summary
          className={buttonClass("secondary", "md", "rt-control cursor-pointer list-none")}
          title="Options for the next Find jobs only; not saved"
        >
          Search options{limit || dryRun || ageDays != null ? " •" : ""}
        </summary>
        <div className="absolute right-0 z-20 mt-1 w-72 space-y-3 rounded-sm border border-line bg-chrome p-3 text-sm shadow-lg">
          <p className="rt-eyebrow">This search only (not saved)</p>
          <div>
            <p className="mb-1">Postings from the last</p>
            <AgeWindowPicker
              ariaLabel="Posting age for this search"
              value={ageDays ?? apply.max_age_days}
              onChange={(days) =>
                onOptions({ ...options, ageDays: days === apply.max_age_days ? null : days })
              }
            />
            <p className="mt-1 text-xs text-ink-muted">
              Postings you've already found are skipped. Each search still stops at the most
              postings per search below.
            </p>
          </div>
          <label className="block">
            Most postings per search
            <input
              className="field mt-1 w-24"
              type="number"
              min={1}
              max={500}
              placeholder={String(apply.max_new_per_day)}
              value={limit}
              onChange={(e) => onOptions({ ...options, limit: e.target.value })}
            />
          </label>
          <label className="flex items-center gap-2">
            <Switch checked={dryRun} onChange={(on) => onOptions({ ...options, dryRun: on })} />
            Only list what's found (don't tailor)
          </label>
        </div>
      </details>
      <a className={buttonClass("outline", "md", "rt-control")} href={applicationsExportUrl()}>
        Export CSV
      </a>
      <Button
        disabled={busy || active || !anySource}
        title={anySource ? "Look for new postings now" : "Choose what to search for first"}
        onClick={onFind}
      >
        Find jobs
      </Button>
    </>
  );
}

/** In progress tab, selection bar: Prepare, Tailor again and Fill for the checked rows. */
export function ProgressBulkActions({
  selected,
  busy,
  active,
  browserConnected,
  onPrepare,
  onRetailor,
  onFill,
}: {
  selected: ApplicationRow[];
  busy: boolean;
  active: boolean;
  browserConnected: boolean;
  onPrepare: (ids: string[]) => void;
  onRetailor: (rows: ApplicationRow[]) => void;
  onFill: (ids: string[]) => void;
}) {
  const prepareIds = selected
    .filter((row) => !TERMINAL_STATUSES.has(row.status))
    .map((row) => row.source_job_id);
  const retailorRows = selected.filter(canRetailor);
  const fillIds = selected
    .filter((row) => row.status === "ready" && canFillAfterReview(row))
    .map((row) => row.source_job_id);
  const idleNote = active ? "Available when the current Apply task finishes" : undefined;
  return (
    <>
      <Button
        size="sm"
        disabled={busy || active || !prepareIds.length}
        title={idleNote ?? GLOSSARY.prepare.help}
        onClick={() => onPrepare(prepareIds)}
      >
        {GLOSSARY.prepare.label} ({prepareIds.length})
      </Button>
      <Button
        size="sm"
        disabled={busy || active || !retailorRows.length}
        title={
          idleNote ?? "Tailor the selected applications again, replacing files that already exist."
        }
        onClick={() => onRetailor(retailorRows)}
      >
        Tailor again ({retailorRows.length})
      </Button>
      <Button
        size="sm"
        variant="primary"
        disabled={busy || active || !fillIds.length || !browserConnected}
        title={
          idleNote ??
          (browserConnected
            ? "Open and fill the selected postings"
            : "Connect the browser in Apply settings first")
        }
        onClick={() => onFill(fillIds)}
      >
        Fill ({fillIds.length})
      </Button>
    </>
  );
}

/** In progress tab, a quiet line: what Fill does, the sources' last run, and blockers. */
export function ProgressNote({
  apply,
  sourcesStatus,
  selected,
}: {
  apply: ApplySettings;
  sourcesStatus: SourcesStatus | null;
  /** The checked rows; the line says why any of them cannot be filled. */
  selected: ApplicationRow[];
}) {
  const blockers = fillBlockers(selected);
  const allowedAts = apply.auto_submit_ats;
  return (
    <div className="space-y-1 text-xs text-ink-muted">
      <p>
        {sourcesHeadline(apply.sources, sourcesStatus?.last_run_at)} ·{" "}
        {apply.auto_submit_enabled && allowedAts.length
          ? `Fill submits verified forms on ${allowedAts.join(", ")}`
          : "Fill stops for your review before submitting"}
      </p>
      {blockers && <p className="text-attn">{blockers}</p>}
    </div>
  );
}
