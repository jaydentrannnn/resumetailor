import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { AppConfig, JobSettings } from "../../api";
import { Button, Tile } from "../../components/ui";
import { runOptionsSummary } from "../../lib/runOptionsSummary";
import { RunOptionsForm } from "./RunOptionsForm";
import { RunOptionsSummary } from "./RunOptionsSummary";

/**
 * The Options tile. Collapsed it is a one-line summary (`RunOptionsSummary`); "Change"
 * opens the full form (`RunOptionsForm`) in the same tile. The AI model is chosen in
 * Settings; this tile only names it.
 */
export function RunOptions({
  config,
  settings,
  onChange,
  disabled,
  workspaceId,
  saveNotice,
}: {
  config: AppConfig | null;
  settings: JobSettings;
  onChange: (s: JobSettings) => void;
  disabled: boolean;
  workspaceId: string;
  saveNotice: React.ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const formId = useId();
  const { provider, modelName } = runOptionsSummary(settings, config);

  return (
    <Tile
      title="Options"
      aria-label="Options"
      actions={
        <Button
          size="sm"
          aria-expanded={editing}
          aria-controls={formId}
          onClick={() => setEditing((on) => !on)}
        >
          {editing ? "Done" : "Change"}
        </Button>
      }
    >
      {saveNotice}
      {editing ? (
        <div id={formId}>
          <p className="mb-4 text-sm text-ink-muted">
            Using <strong className="font-medium text-ink">{provider}</strong>
            {modelName && <span className="ml-1.5 font-mono text-xs">{modelName}</span>}
            {" · "}
            <Link to="/settings?tab=models" className="rt-link font-medium">
              Change model in Settings
            </Link>
          </p>
          <RunOptionsForm
            config={config}
            settings={settings}
            onChange={onChange}
            disabled={disabled}
            workspaceId={workspaceId}
          />
        </div>
      ) : (
        <RunOptionsSummary config={config} settings={settings} />
      )}
    </Tile>
  );
}
