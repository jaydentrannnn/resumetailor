import { useEffect, useState, type ReactNode } from "react";
import { fetchModelQueue, type ModelQueueStatus } from "../../api";
import { Card, Switch } from "../../components/ui";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import { useRunState } from "../../state/runState";
import { AiAdvancedSettings } from "./AiAdvancedSettings";
import { ModelRow } from "./ModelRow";
import type { RoleModel } from "./useRoleModel";
import { VertexConnectionPanel } from "./VertexConnectionPanel";
import { withAdvanced } from "../../lib/advancedSettings";

/**
 * The one AI models tile: provider, model and plan for Light and Heavy work, each with
 * its connection test and rate-limit state. Keys live below. With `advanced`, a switch in
 * the header enables saved effort, posting reads, request speed and resumes at once.
 */
export function ModelsCard({
  light,
  heavy,
  advanced = false,
  embedded = false,
  className = "",
  description = "Pick a provider and model for each kind of work. Connections are tested automatically.",
}: {
  light: RoleModel;
  heavy: RoleModel;
  /** Offer the Advanced switch (Settings; not the setup wizard). */
  advanced?: boolean;
  embedded?: boolean;
  className?: string;
  description?: ReactNode;
}) {
  const { settingsLoaded, settings, setSettings } = useRunState();
  const showAdvanced = settings.ai_advanced_enabled ?? true;
  const queue = useModelQueue();
  const toggle = (on: boolean) => {
    setSettings(withAdvanced(settings, on));
  };
  return (
    <Card
      embedded={embedded}
      className={className}
      title="AI models"
      description={description}
      actions={
        advanced && (
          <label className="flex items-center gap-2 text-[13px] font-semibold">
            <Switch checked={showAdvanced} onChange={toggle} disabled={!settingsLoaded} />
            Advanced
          </label>
        )
      }
    >
      <fieldset disabled={!settingsLoaded} className="min-w-0 divide-y divide-line">
        <legend className="sr-only">AI models</legend>
        <ModelRow model={light} queue={queue} />
        <ModelRow model={heavy} queue={queue} />
      </fieldset>
      {[light, heavy].some((m) => m.selection.provider === "vertex_ai") && (
        <VertexConnectionPanel />
      )}
      {advanced && showAdvanced && (
        <div className="mt-4 border-t border-line pt-4">
          <AiAdvancedSettings />
        </div>
      )}
    </Card>
  );
}

/** The request queue's live state, for each row's "at limit" chip. */
function useModelQueue(): ModelQueueStatus | null {
  const [status, setStatus] = useState<ModelQueueStatus | null>(null);
  useEffect(() => {
    let live = true;
    const poll = startAdaptivePoll(async () => {
      const next = await fetchModelQueue();
      if (live) setStatus(next);
      return next.endpoints.some(
        (e) => e.active || e.waiting || e.cooldown_seconds > 0 || (e.exhausted_seconds ?? 0) > 0,
      );
    });
    return () => {
      live = false;
      poll.stop();
    };
  }, []);
  return status;
}
