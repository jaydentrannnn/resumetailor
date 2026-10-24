import { useRunState } from "../../state/runState";
import { EffortSetting } from "./EffortSetting";
import { ModelSpeedSetting } from "./ModelSpeedSetting";
import { SELECT_WIDTH } from "./selectWidth";
import { SettingRow } from "../../components/ui";

/** Tuning most people leave alone, shown inside the AI models tile when Advanced is on. */
export function AiAdvancedSettings() {
  const { settings, setSettings } = useRunState();
  return (
    <div>
      <EffortSetting />
      <SettingRow
        label="Job posting reads"
        layout="action"
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
        layout="action"
        description="How many tailoring runs may work at the same time. Above 4 suits paid cloud models; a model on this computer still answers one request at a time."
      >
        <select
          className={`field ${SELECT_WIDTH}`}
          aria-label="Resumes at once"
          value={settings.max_concurrent_jobs}
          onChange={(e) =>
            setSettings({ ...settings, max_concurrent_jobs: Number(e.target.value) })
          }
        >
          {[1, 2, 3, 4, 5, 6, 7, 8].map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </SettingRow>
    </div>
  );
}
