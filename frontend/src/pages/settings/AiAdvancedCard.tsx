import { useId, useState } from "react";
import { Card } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { ModelSpeedSetting } from "./ModelSpeedSetting";
import { SELECT_WIDTH } from "./selectWidth";
import { SettingRow } from "./SettingRow";

/** Tuning most people leave alone, collapsed until asked for. */
export function AiAdvancedCard() {
  const { settings, setSettings } = useRunState();
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  return (
    <Card
      title="Advanced"
      description="Most people never need these. The defaults are tuned for each provider."
      actions={
        <button
          type="button"
          aria-expanded={open}
          aria-controls={bodyId}
          onClick={() => setOpen((o) => !o)}
          className="text-[13px] font-semibold text-ink hover:text-ink-2"
        >
          {open ? "Hide ▾" : "Show ▸"}
        </button>
      }
    >
      {open && (
        <div id={bodyId}>
          <SettingRow
            label="Job posting reads"
            layout="split"
            description="How many times the AI reads each posting and compares notes. More reads catch more requirements but take longer."
          >
            <select
              className={`field ${SELECT_WIDTH}`}
              aria-label="Job posting reads"
              value={settings.extract_runs}
              onChange={(e) => setSettings({ ...settings, extract_runs: Number(e.target.value) })}
            >
              <option value={0}>Automatic (recommended)</option>
              <option value={1}>1 — quick</option>
              <option value={3}>3 — standard</option>
              <option value={5}>5 — thorough</option>
            </select>
          </SettingRow>
          <ModelSpeedSetting />
          <SettingRow
            label="Resumes at once"
            layout="split"
            description="How many tailoring runs may work at the same time. Each one still waits for the speed limit above."
          >
            <select
              className={`field ${SELECT_WIDTH}`}
              aria-label="Resumes at once"
              value={settings.max_concurrent_jobs}
              onChange={(e) =>
                setSettings({ ...settings, max_concurrent_jobs: Number(e.target.value) })
              }
            >
              {[1, 2, 3, 4].map((count) => (
                <option key={count} value={count}>
                  {count}
                </option>
              ))}
            </select>
          </SettingRow>
        </div>
      )}
    </Card>
  );
}
