import type { SecretState } from "../../api";
import {
  modelsFor,
  selectionReady,
  withSelection,
  type ModelRole,
  type ModelSelection,
} from "../../lib/aiModels";
import { useRunState } from "../../state/runState";
import { useModelCheck } from "./useModelCheck";
import { useModelConnection } from "./useModelConnection";

export type RoleModel = ReturnType<typeof useRoleModel>;

/**
 * One task model's selection, connection (keys, local models) and automatic test. Held by
 * the page so the model tile and the API keys card share one test per role.
 */
export function useRoleModel(role: ModelRole, secrets: SecretState[]) {
  const { settings, setSettings, settingsLoaded } = useRunState();
  const selection = modelsFor(settings)[role];
  const connection = useModelConnection(role, selection, secrets);
  const ready = selectionReady(selection);
  const { check, retest } = useModelCheck(
    role,
    settings,
    settingsLoaded && ready && !connection.needsKey,
  );
  const patch = (fields: Partial<ModelSelection>) =>
    setSettings(withSelection(settings, role, { ...selection, ...fields }));
  return { role, selection, connection, ready, check, retest, patch };
}
