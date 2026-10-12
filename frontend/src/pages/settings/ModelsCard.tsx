import type { ReactNode } from "react";
import { Card } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { ModelRow } from "./ModelRow";
import type { RoleModel } from "./useRoleModel";

/** The one AI models tile: provider and model for Light and Heavy work. Keys live below. */
export function ModelsCard({
  light,
  heavy,
  embedded = false,
  className = "",
  description = "Pick a provider and model for each kind of work. Connections are tested automatically.",
}: {
  light: RoleModel;
  heavy: RoleModel;
  embedded?: boolean;
  className?: string;
  description?: ReactNode;
}) {
  const { settingsLoaded } = useRunState();
  return (
    <Card embedded={embedded} className={className} title="AI models" description={description}>
      <fieldset disabled={!settingsLoaded} className="min-w-0 divide-y divide-line">
        <legend className="sr-only">AI models</legend>
        <ModelRow model={light} />
        <ModelRow model={heavy} />
      </fieldset>
    </Card>
  );
}
