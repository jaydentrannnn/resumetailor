import { useState } from "react";
import { importPayData, type PayPreview } from "../../api";
import { Button, Field, Modal } from "../../components/ui";
import { describe } from "../../lib/errors";
import { FIELD_LABELS, missingColumns } from "../../lib/payImport";
import { useToast } from "../../lib/toast";

/**
 * Confirm which column holds each field, then import. Rows without a role, currency,
 * pay period or pay figures are rejected and counted; nothing is guessed.
 */
export function PayImportDialog({
  file,
  preview,
  onClose,
  onImported,
}: {
  file: File;
  preview: PayPreview;
  onClose: () => void;
  onImported: () => void;
}) {
  const toast = useToast();
  const [mapping, setMapping] = useState(preview.mapping);
  const [source, setSource] = useState("");
  const [asOf, setAsOf] = useState("");
  const [busy, setBusy] = useState(false);
  const missing = missingColumns(mapping);

  async function save() {
    setBusy(true);
    try {
      const name = file.name.replace(/\.[^.]+$/, "");
      const saved = await importPayData(file, mapping, { name, source, as_of: asOf });
      const rows = (n: number) => `${n} ${n === 1 ? "row" : "rows"}`;
      const rejected = saved.rejected_count ? `; ${rows(saved.rejected_count)} skipped` : "";
      toast.success(`Imported ${rows(saved.row_count)}${rejected}`);
      onImported();
    } catch (reason) {
      toast.error("Could not import", describe(reason).detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Import ${file.name}`} onClose={onClose} size="lg">
      <div className="space-y-4 text-[13px]">
        <p className="text-xs text-ink-muted">
          {preview.total_rows} rows. Check which column holds each field; a row without a role,
          currency, pay period or pay figures is skipped. Hourly and yearly pay are never converted.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          {FIELD_LABELS.map(([key, label]) => (
            <Field key={key} label={label}>
              <select
                className="field text-xs"
                value={mapping[key]}
                onChange={(e) => setMapping({ ...mapping, [key]: e.target.value })}
              >
                <option value="">None</option>
                {preview.columns.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
            </Field>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Where it is from">
            <input
              className="field text-xs"
              placeholder="e.g. Career centre salary survey"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            />
          </Field>
          <Field label="As of">
            <input
              type="date"
              className="field text-xs"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
            />
          </Field>
        </div>
        <div className="overflow-x-auto rounded-sm border border-line">
          <table className="w-full text-xs">
            <thead className="bg-sunken text-left text-ink-2">
              <tr>
                {preview.columns.map((column) => (
                  <th key={column} className="px-2 py-1 font-medium">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, index) => (
                <tr key={index} className="border-t border-line">
                  {row.map((cell, i) => (
                    <td key={i} className="max-w-48 truncate px-2 py-1 text-ink-muted">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {missing && <span className="mr-auto text-xs text-attn">{missing}</span>}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || Boolean(missing)} onClick={() => void save()}>
            Import
          </Button>
        </div>
      </div>
    </Modal>
  );
}
