import { applicationsExportUrl, type ApplySettings, type SourcesStatus } from "../../api";
import { Button } from "../../components/ui";
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

/** In progress tab: Find jobs and its options, plus Prepare / Tailor again / Fill for the selection. */
export function ProgressToolbar({
  apply,
  sourcesStatus,
  options,
  onOptions,
  busy,
  active,
  anySource,
  browserConnected,
  prepareCount,
  retailorCount,
  fillCount,
  blockers,
  onFind,
  onPrepare,
  onRetailor,
  onFill,
  onManageSources,
}: {
  apply: ApplySettings;
  sourcesStatus: SourcesStatus | null;
  options: FindOptions;
  onOptions: (next: FindOptions) => void;
  busy: boolean;
  active: boolean;
  anySource: boolean;
  browserConnected: boolean;
  prepareCount: number;
  retailorCount: number;
  fillCount: number;
  blockers: string | null;
  onFind: () => void;
  onPrepare: () => void;
  onRetailor: () => void;
  onFill: () => void;
  onManageSources: () => void;
}) {
  const { limit, dryRun, ageDays } = options;
  const idleNote = active ? "Available when the current Apply task finishes" : undefined;
  const allowedAts = apply.auto_submit_ats;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-panel p-3 text-sm">
      <Button
        variant="secondary"
        disabled={busy || active || !anySource}
        title={anySource ? "Look for new postings now" : "Choose what to search for first"}
        onClick={onFind}
      >
        Find jobs
      </Button>
      <details className="relative">
        <summary
          className="rt-control inline-flex cursor-pointer items-center rounded-md border border-line bg-panel px-3 text-sm"
          title="Options for the next Find jobs only; not saved"
        >
          Search options{limit || dryRun || ageDays != null ? " •" : ""}
        </summary>
        <div className="absolute left-0 z-20 mt-1 w-72 space-y-3 rounded-md border border-line bg-panel p-3 text-sm shadow-lg">
          <p className="text-xs font-medium text-ink-muted">This search only (not saved)</p>
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
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => onOptions({ ...options, dryRun: e.target.checked })}
            />
            Only list what's found (don't tailor)
          </label>
        </div>
      </details>
      <a
        className="rt-control inline-flex items-center rounded-md border border-line bg-panel px-3 font-medium text-ink hover:border-line-hover"
        href={applicationsExportUrl()}
      >
        Export CSV
      </a>
      <span aria-hidden className="mx-1 h-6 w-px bg-line" />
      <Button
        variant="secondary"
        disabled={busy || active || !prepareCount}
        title={idleNote ?? GLOSSARY.prepare.help}
        onClick={onPrepare}
      >
        {GLOSSARY.prepare.label} ({prepareCount})
      </Button>
      <Button
        variant="secondary"
        disabled={busy || active || !retailorCount}
        title={
          idleNote ?? "Tailor the selected applications again, replacing files that already exist."
        }
        onClick={onRetailor}
      >
        Tailor again ({retailorCount})
      </Button>
      <Button
        variant="primary"
        disabled={busy || active || !fillCount || !browserConnected}
        title={
          idleNote ??
          (browserConnected
            ? "Open and fill the selected postings"
            : "Connect the browser in Apply settings first")
        }
        onClick={onFill}
      >
        Fill ({fillCount})
      </Button>
      <span className="ml-auto text-xs text-ink-muted">
        {apply.auto_submit_enabled && allowedAts.length
          ? `Fill submits verified forms on ${allowedAts.join(", ")}`
          : "Fill stops for your review before submitting"}
      </span>
      <p className="w-full text-xs text-ink-muted">
        {sourcesHeadline(apply.sources, sourcesStatus?.last_run_at)} ·{" "}
        <button type="button" className="text-accent underline" onClick={onManageSources}>
          Manage
        </button>
      </p>
      {blockers && <p className="w-full text-xs text-warn">{blockers}</p>}
    </div>
  );
}
