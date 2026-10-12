import type { ModelPlan, ModelSelection } from "../../lib/aiModels";
import { PLAN_OPTIONS } from "../../lib/modelLimits";

type Patch = (fields: Partial<ModelSelection>) => void;

/** A custom server's API format and URL, beside its model name. The key stays in API keys. */
export function CustomServerFields({
  selection,
  patch,
}: {
  selection: ModelSelection;
  patch: Patch;
}) {
  return (
    <>
      <label className="block min-w-0 text-sm font-medium">
        API format
        <select
          className="field mt-1"
          value={selection.api_format}
          onChange={(e) => patch({ api_format: e.target.value as ModelSelection["api_format"] })}
        >
          <option value="openai">OpenAI-compatible</option>
          <option value="anthropic">Anthropic-compatible</option>
        </select>
      </label>
      <label className="block min-w-0 text-sm font-medium">
        Server URL
        <input
          className="field mt-1 font-mono"
          type="url"
          value={selection.base_url}
          placeholder={
            selection.api_format === "openai"
              ? "https://server.example/v1"
              : "https://server.example"
          }
          onChange={(e) => patch({ base_url: e.target.value })}
        />
      </label>
    </>
  );
}

/** How the model is paid for, which sets how many of its requests run at once. */
export function PlanField({ selection, patch }: { selection: ModelSelection; patch: Patch }) {
  return (
    <label className="block min-w-0 text-sm font-medium">
      Plan
      <select
        className="field mt-1"
        value={selection.plan ?? ""}
        onChange={(e) => patch({ plan: (e.target.value || null) as ModelPlan | null })}
      >
        {PLAN_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-xs font-normal text-ink-muted">
        Sets how many requests go at once (a free tier gets one).
      </span>
    </label>
  );
}
