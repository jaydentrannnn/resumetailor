import { useState } from "react";
import type { ApplyFieldOutcome, ApplyReviewField } from "../api";

export function observedFieldValue(field: ApplyReviewField): string {
  const selected = field.options.filter((option) => option.selected && !option.placeholder);
  if (selected.length > 0) return selected.map((option) => option.label).join(", ");
  if (field.control_kind === "combobox" && field.selection_state !== "committed") return field.current_value ? `${field.current_value} (search text; no option selected)` : "No option selected";
  return field.current_value || "Blank";
}

export function FieldCorrectionRow({ field, outcome, disabled, onCorrect }: {
  field: ApplyReviewField;
  outcome?: ApplyFieldOutcome;
  disabled: boolean;
  onCorrect: (field: ApplyReviewField, value: string | null, optionIds: string[]) => void;
}) {
  const [value, setValue] = useState(field.current_value || "");
  const [optionId, setOptionId] = useState("");
  const choice = ["native_select", "combobox", "radio_group"].includes(field.control_kind);
  const text = ["text", "textarea", "date", "number"].includes(field.control_kind);
  const canonical = outcome?.canonical_key || field.canonical_key || "";
  const browserOnly = /agreement|signature|credential|password|consent|attest|certif|terms/.test(`${canonical} ${field.label}`.toLowerCase()) || field.constraints?.input_type === "password" || field.control_kind === "file" || field.enabled === false;
  const canCorrect = !browserOnly && (text || (choice && field.options.some((option) => option.enabled && !option.placeholder)));
  const rawLimit = field.constraints?.maxlength ?? field.constraints?.max_length;
  const maxLength = typeof rawLimit === "number" && rawLimit >= 0 ? Math.min(rawLimit, 5000) : 5000;
  const invalidValue = value.length > maxLength || (field.control_kind === "number" && value !== "" && !Number.isFinite(Number(value))) || (field.control_kind === "date" && value !== "" && !/^\d{4}-\d{2}-\d{2}$/.test(value));
  const canSubmit = choice ? Boolean(optionId) : value !== field.current_value && !invalidValue;
  const reason = outcome?.reason_text || outcome?.reason_code?.replaceAll("_", " ") || (outcome?.state === "preserved" ? "Existing answer retained; personal fact not independently verified" : outcome?.state === "verified_filled" ? "Filled value verified on the form" : "Needs review");
  const inputProps = {
    className: "min-w-44 rounded border border-line bg-bg px-2 py-1 disabled:opacity-50",
    value, disabled, maxLength, "aria-label": `Correct ${field.label}`,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setValue(event.target.value),
  };
  return (
    <li className="rounded border border-line bg-panel p-2.5 text-xs">
      <p className="font-medium text-ink">{field.label || "Unlabeled field"} · {field.required ? "Required" : "Optional"}</p>
      <p className="mt-1 whitespace-pre-wrap text-ink-muted">Current: {observedFieldValue(field)} · {reason}</p>
      {outcome?.answer_source && <p className="mt-1 text-ink-muted">Source: {outcome.answer_source.replaceAll("_", " ")}</p>}
      {canCorrect ? <div className="mt-2 flex flex-wrap items-center gap-2">
        {choice ? (
          <select className="min-w-44 rounded border border-line bg-bg px-2 py-1 disabled:opacity-50" value={optionId} disabled={disabled} onChange={(event) => setOptionId(event.target.value)} aria-label={`Correct ${field.label}`}>
            <option value="">Choose an observed option</option>
            {field.options.filter((option) => option.enabled && !option.placeholder).map((option) => <option key={option.option_id} value={option.option_id}>{option.label}</option>)}
          </select>
        ) : field.control_kind === "textarea" ? <textarea {...inputProps} rows={3} /> : <input {...inputProps} type={field.control_kind === "date" || field.control_kind === "number" ? field.control_kind : "text"} />}
        <button type="button" className="rounded border border-accent px-2 py-1 text-accent disabled:opacity-50" disabled={disabled || !canSubmit} onClick={() => onCorrect(field, choice ? null : value, choice ? [optionId] : [])}>Apply correction</button>
        {invalidValue && <span role="alert" className="text-danger">Enter a valid value within {maxLength} characters.</span>}
      </div> : <p className="mt-1 text-ink-muted">Review in browser</p>}
    </li>
  );
}
