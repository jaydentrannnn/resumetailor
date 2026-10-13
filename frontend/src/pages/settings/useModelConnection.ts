import { useEffect, useState } from "react";
import { fetchLocalModels, fetchSecretState, type SecretState } from "../../api";
import {
  customCredentialName,
  selectionProvider,
  type ModelRole,
  type ModelSelection,
} from "../../lib/aiModels";
import { useVertexConnection } from "./useVertexConnection";

export function useModelConnection(
  role: ModelRole,
  selection: ModelSelection,
  secrets: SecretState[],
) {
  const [local, setLocal] = useState<{ reachable: boolean; models: string[] } | null>(null);
  const [custom, setCustom] = useState<SecretState | null>(null);
  const provider = selectionProvider(selection);
  const { provider: id, api_format, base_url } = selection;
  const vertex = useVertexConnection(id === "vertex_ai");
  useEffect(() => {
    let live = true;
    setLocal(null);
    if (id === "ollama" || id === "lmstudio") {
      fetchLocalModels(id)
        .then((res) => {
          if (live) setLocal(res);
        })
        .catch(() => {
          if (live) setLocal({ reachable: false, models: [] });
        });
    }
    return () => {
      live = false;
    };
  }, [id]);
  useEffect(() => {
    let live = true;
    setCustom(null);
    if (id === "custom" && /^https?:\/\//.test(base_url)) {
      void customCredentialName(role, { provider: id, api_format, base_url, model_name: "" })
        .then(async (name) => ({ name, state: await fetchSecretState(name) }))
        .then(({ state }) => {
          if (live) setCustom(state);
        })
        .catch(() => undefined);
    }
    return () => {
      live = false;
    };
  }, [role, id, api_format, base_url, secrets]);
  const keys =
    id === "custom"
      ? custom
        ? [custom]
        : []
      : (provider?.keys ?? []).map(
          (name) => secrets.find((s) => s.name === name) ?? { name, set: false, source: null },
        );
  const needsKey = id !== "custom" && !!provider?.keys.length && !keys.some((key) => key.set);
  return { provider, local, keys, needsKey, vertex: id === "vertex_ai" ? vertex : null };
}
