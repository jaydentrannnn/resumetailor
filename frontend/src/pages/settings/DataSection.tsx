import { useCallback, useEffect, useRef, useState } from "react";
import {
  clearCache,
  exportDataUrl,
  fetchCacheUsage,
  fetchDataInfo,
  importData,
  resetData,
  type CacheUsage,
  type DataInfo,
} from "../../api";
import { CopyButton } from "../../components/CopyButton";
import { Button, Card, Modal } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { describe } from "../../lib/errors";
import { formatBytes } from "../../lib/format";
import { useToast } from "../../lib/toast";
import { useWorkspaceState } from "../../state/workspaceState";
import { SettingRow } from "./SettingRow";

const MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024;

/** Settings → Data: where files live, export/import, cache, and "delete all data". */
export function DataSection() {
  const toast = useToast();
  const { activate, refresh } = useWorkspaceState();
  const [info, setInfo] = useState<DataInfo | null>(null);
  const [cache, setCache] = useState<CacheUsage | null>(null);
  const [includeOutput, setIncludeOutput] = useState(true);
  const [importing, setImporting] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    fetchDataInfo()
      .then(setInfo)
      .catch(() => setInfo(null));
    fetchCacheUsage()
      .then(setCache)
      .catch(() => setCache(null));
  }, []);
  useEffect(load, [load]);

  async function onImport(file: File) {
    if (file.size > MAX_IMPORT_BYTES) {
      toast.error("Import failed", "This file is larger than 2 GB.");
      if (fileInput.current) fileInput.current.value = "";
      return;
    }
    setImporting(true);
    try {
      const created = await importData(file);
      await refresh();
      toast.success(`Imported as "${created.label}"`, "It is a separate profile.", {
        label: "Switch to it",
        onClick: () => void activate(created.id),
      });
    } catch (err) {
      const d = describe(err);
      toast.error("Import failed", d.detail);
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onClearCache() {
    setClearing(true);
    try {
      const res = await clearCache();
      toast.success("Cache cleared", `${res.removed} saved results removed.`);
      load();
    } catch (err) {
      toast.error("Could not clear the cache", describe(err).detail);
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Where your data lives" description="Everything stays on this computer.">
        {info ? (
          <dl className="space-y-2 text-sm">
            {[
              ["Profile data", info.data_dir, info.data_bytes],
              ["Generated files", info.output_dir, info.output_bytes],
              ["Templates", info.templates_dir, null],
            ].map(([label, path, bytes]) => (
              <div
                key={label as string}
                className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2"
              >
                <dt className="shrink-0 text-ink-muted sm:w-32">
                  {label}
                  {bytes !== null && (
                    <span className="ml-2 text-xs sm:hidden">{formatBytes(bytes as number)}</span>
                  )}
                </dt>
                <dd className="flex min-w-0 flex-1 items-center gap-2">
                  <code
                    className="min-w-0 flex-1 truncate font-mono text-xs text-ink"
                    title={path as string}
                  >
                    {path}
                  </code>
                  <CopyButton label="Copy path" text={path as string} />
                  {bytes !== null && (
                    <span className="hidden whitespace-nowrap text-xs text-ink-muted sm:inline">
                      {formatBytes(bytes as number)}
                    </span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-sm text-ink-muted">Loading…</p>
        )}
      </Card>

      <Card title="Back up or move to another computer">
        <SettingRow
          label="Export and import"
          description="Export saves this profile as one .zip file. Import adds a zip as a new profile and never overwrites an existing one (up to 2 GB)."
        >
          <div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeOutput}
                onChange={(e) => setIncludeOutput(e.target.checked)}
              />
              Include generated resumes and cover letters
            </label>
            <p className="mt-2 text-xs text-ink-muted">
              API keys and passwords are never included. Enter them again on the new computer.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a className={buttonClass("primary")} href={exportDataUrl(includeOutput)} download>
                Export this profile
              </a>
              <Button loading={importing} onClick={() => fileInput.current?.click()}>
                Import from a .zip
              </Button>
              <input
                ref={fileInput}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                aria-label="Choose an export .zip to import"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void onImport(file);
                }}
              />
            </div>
          </div>
        </SettingRow>
      </Card>

      <Card title="Saved AI results">
        <SettingRow
          label="Cache"
          description={
            <>
              <p>
                Results are reused when you tailor for the same posting again, which saves time and
                money. Clearing them is safe.
              </p>
              <p className="mt-2 font-mono">
                {cache ? `${cache.files} saved results · ${formatBytes(cache.bytes)}` : "…"}
              </p>
            </>
          }
        >
          <Button onClick={onClearCache} loading={clearing} disabled={!cache?.files}>
            Clear cache
          </Button>
        </SettingRow>
      </Card>

      <Card title="Delete all data">
        <SettingRow
          label="This profile"
          description="Removes this profile's resume, templates, applications and files."
        >
          <Button variant="danger" onClick={() => setResetOpen(true)}>
            Delete all data…
          </Button>
        </SettingRow>
      </Card>
      {resetOpen && <ResetDialog onClose={() => setResetOpen(false)} onDone={load} />}
    </div>
  );
}

function ResetDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  async function confirm() {
    setBusy(true);
    try {
      const res = await resetData(typed);
      toast.success("All data deleted", `A copy was kept in ${res.trash} in case you need it.`);
      onClose();
      onDone();
      window.location.assign("/");
    } catch (err) {
      toast.error("Nothing was deleted", describe(err).detail);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Delete all data in this profile?" onClose={onClose}>
      <p className="text-sm text-ink">
        Your master resume, templates, applications, settings and generated files will be removed
        from this profile. A copy is moved to a trash folder inside your data folder, so it can be
        recovered by hand.
      </p>
      <label className="mt-4 block text-sm">
        Type <strong>DELETE</strong> to confirm
        <input
          className="field mt-1"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
        />
      </label>
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" disabled={typed !== "DELETE"} loading={busy} onClick={confirm}>
          Delete everything
        </Button>
      </div>
    </Modal>
  );
}
