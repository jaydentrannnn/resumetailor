import type { ApplySettings } from "../../api";
import { AUTOFILL_PROVIDERS } from "../../lib/providers";

/** Provider and model for Fill's own calls (the Autofill model), separate from Tailor's. */
export function AutofillModelFields({
  apply,
  patch,
}: {
  apply: ApplySettings;
  patch: (fields: Partial<ApplySettings>) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-sm">
        <span className="mb-1 block">Provider</span>
        <select
          className="field w-full"
          value={apply.model_provider}
          onChange={(e) => patch({ model_provider: e.target.value as typeof apply.model_provider })}
        >
          {AUTOFILL_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="mb-1 block">Model</span>
        <input
          className="field w-full font-mono"
          value={apply.model_name}
          onChange={(e) => patch({ model_name: e.target.value })}
        />
      </label>
    </div>
  );
}
