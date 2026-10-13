import { EditableSelect } from "./EditableSelect";
import type { RoleModel } from "./useRoleModel";

export function VertexModelField({ model }: { model: RoleModel }) {
  const { selection, connection, patch } = model;
  return (
    <EditableSelect
      label="Model"
      value={selection.model_name.replace(/^vertex_ai\//, "")}
      options={(connection.vertex?.models ?? []).map((entry) => ({
        value: entry.id,
        label: entry.name ?? entry.id,
        group: entry.publisher,
      }))}
      placeholder="Choose a model"
      customLabel="Custom model ID"
      onChange={(model_name) => patch({ model_name })}
    />
  );
}
