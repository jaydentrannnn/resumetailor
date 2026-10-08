import { SettingRow } from "./SettingRow";
import { buttonClass } from "../../lib/buttonClass";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ResumeHistoryList } from "../../components/ResumeHistoryList";
import { Card } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { ModelQueueCard } from "./ModelQueueCard";

/** Settings → Advanced: extraction votes, vocabulary, and master resume history. */
export function AdvancedSection() {
  const { settings, setSettings } = useRunState();
  return (
    <div className="space-y-4">
      <ModelQueueCard />
      <Card title="Tailoring and writing">
        <SettingRow
          label="Job description reading"
          description="How many times the AI reads each posting before agreeing on its requirements. More reads are steadier but slower and cost more on paid models."
        >
          <select
            className="field"
            aria-label="Job description reads"
            value={settings.extract_runs}
            onChange={(e) => setSettings({ ...settings, extract_runs: Number(e.target.value) })}
          >
            <option value={0}>Automatic (1 on paid models, 3 on local ones)</option>
            <option value={1}>1 read</option>
            <option value={3}>3 reads</option>
            <option value={5}>5 reads</option>
          </select>
        </SettingRow>
        <SettingRow
          label="Concurrent tailoring runs"
          description="How many tailoring jobs may run together. PDF conversion is queued separately."
        >
          <select
            className="field"
            aria-label="Concurrent tailoring runs"
            value={settings.max_concurrent_jobs}
            onChange={(e) =>
              setSettings({ ...settings, max_concurrent_jobs: Number(e.target.value) })
            }
          >
            {[1, 2, 3, 4].map((count) => (
              <option key={count} value={count}>
                {count} run{count === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        </SettingRow>
        <SettingRow
          label="Skill vocabulary"
          description="Teach ResumeTailor that different spellings mean the same skill (for example, “MS Excel” and “Excel”)."
        >
          <Link to="/vocabulary" className={buttonClass("secondary", "sm")}>
            Open vocabulary
          </Link>
        </SettingRow>
      </Card>
      <ResumeHistory />
    </div>
  );
}

function ResumeHistory() {
  const [keep, setKeep] = useState(50);
  return (
    <Card
      title="Master resume history"
      description={`Every save is kept (the last ${keep}). Restore an earlier version if an edit or import went wrong.`}
    >
      <ResumeHistoryList onKeep={setKeep} />
    </Card>
  );
}
