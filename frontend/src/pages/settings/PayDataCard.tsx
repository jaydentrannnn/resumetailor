import { useCallback, useEffect, useRef, useState } from "react";
import {
  deletePayData,
  listPayData,
  previewPayData,
  type PayDataset,
  type PayPreview,
} from "../../api";
import { Button, Card, SettingRow, StatusChip } from "../../components/ui";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { PayImportDialog } from "./PayImportDialog";

const ALL_PROFILES = (
  <StatusChip tone="neutral" mark={false}>
    Every profile
  </StatusChip>
);

function DatasetRow({ dataset, onDelete }: { dataset: PayDataset; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const skipped = dataset.rejected.map((r) => `Row ${r.row}: ${r.reason}`).join("\n");
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[13px]">
      <span className="min-w-0 flex-1">
        <span className="font-medium text-ink">{dataset.name}</span>
        <span className="text-xs text-ink-muted">
          {dataset.source ? ` · ${dataset.source}` : ""}
          {dataset.as_of ? ` · as of ${dataset.as_of}` : ""} · {dataset.row_count} rows
        </span>
        {dataset.rejected_count > 0 && (
          <span className="text-xs text-attn" title={skipped}>
            {" "}
            · {dataset.rejected_count} skipped
          </span>
        )}
      </span>
      {confirming ? (
        <>
          <Button size="sm" variant="danger" onClick={onDelete}>
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Cancel
          </Button>
        </>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>
          Delete…
        </Button>
      )}
    </li>
  );
}

/**
 * Settings → Data: pay data imported from a CSV or XLSX file (a salary survey, a career
 * centre report). App-wide; used only for an application's "Pay for similar roles".
 */
export function PayDataCard() {
  const toast = useToast();
  const [datasets, setDatasets] = useState<PayDataset[] | null>(null);
  const [pending, setPending] = useState<{ file: File; preview: PayPreview } | null>(null);
  const [reading, setReading] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    listPayData()
      .then(setDatasets)
      .catch(() => setDatasets([]));
  }, []);
  useEffect(load, [load]);

  async function pick(file: File) {
    setReading(true);
    try {
      setPending({ file, preview: await previewPayData(file) });
    } catch (reason) {
      toast.error("Could not read the file", describe(reason).detail);
    } finally {
      setReading(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove(dataset: PayDataset) {
    try {
      await deletePayData(dataset.id);
      load();
    } catch (reason) {
      toast.error("Could not delete", describe(reason).detail);
    }
  }

  return (
    <Card title="Pay data" actions={ALL_PROFILES}>
      <SettingRow
        label="Pay ranges"
        description="From a CSV or Excel file, compared with posted ranges on each application's Overview. Never part of your resume."
        layout="action"
      >
        <input
          ref={input}
          type="file"
          accept=".csv,.xlsx,.tsv,.txt"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && void pick(e.target.files[0])}
        />
        <Button variant="plain" disabled={reading} onClick={() => input.current?.click()}>
          {reading ? "Reading…" : "Import a file…"}
        </Button>
      </SettingRow>
      {datasets && datasets.length > 0 && (
        <ul className="mt-3 divide-y divide-line">
          {datasets.map((dataset) => (
            <DatasetRow key={dataset.id} dataset={dataset} onDelete={() => void remove(dataset)} />
          ))}
        </ul>
      )}
      {pending && (
        <PayImportDialog
          file={pending.file}
          preview={pending.preview}
          onClose={() => setPending(null)}
          onImported={() => {
            setPending(null);
            load();
          }}
        />
      )}
    </Card>
  );
}
