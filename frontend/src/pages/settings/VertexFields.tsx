import type { RoleModel } from "./useRoleModel";
import { EditableSelect } from "./EditableSelect";

const LOCATIONS = [
  "global",
  "us",
  "eu",
  "us-central1",
  "us-east1",
  "us-east4",
  "us-east5",
  "us-west1",
  "us-west4",
  "europe-west1",
  "europe-west4",
  "asia-east1",
  "asia-southeast1",
];

export function VertexFields({ model, id }: { model: RoleModel; id: string }) {
  const { selection, patch } = model;
  const vertex = model.connection.vertex;
  const selected = vertex?.models.find(
    (m) => m.id === selection.model_name.replace(/^vertex_ai\//, ""),
  );
  const regions = selected?.locations.length ? selected.locations : LOCATIONS;
  return (
    <>
      <label className="block min-w-0 text-sm font-medium">
        Google Cloud project ID
        <input
          className="field mt-1 font-mono"
          value={selection.vertex_project ?? ""}
          placeholder="Choose or enter your project ID"
          list={`${id}-projects`}
          onChange={(e) => patch({ vertex_project: e.target.value })}
        />
        <datalist id={`${id}-projects`}>
          {vertex?.projects.map((p) => (
            <option key={p.id} value={p.id} />
          ))}
        </datalist>
      </label>
      <EditableSelect
        label="Vertex location"
        value={selection.vertex_location ?? ""}
        options={regions.map((value) => ({
          value,
          label:
            value === "global"
              ? "Global (global)"
              : value === "us"
                ? "United States (us)"
                : value === "eu"
                  ? "European Union (eu)"
                  : value,
        }))}
        placeholder="Choose a location"
        customLabel="Custom location"
        onChange={(vertex_location) => patch({ vertex_location })}
      />
      <p className="text-xs text-ink-muted sm:col-span-2">
        Managed text models only. Availability depends on your project and location.
      </p>
      {vertex?.detail && <p className="text-xs text-ink-muted sm:col-span-2">{vertex.detail}</p>}
    </>
  );
}
