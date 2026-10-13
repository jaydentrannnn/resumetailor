import { useEffect, useState } from "react";
import {
  fetchVertexConnection,
  fetchVertexModels,
  fetchVertexProjects,
  type VertexConnection,
  type VertexModel,
  type VertexProject,
} from "../../api";
import { describe } from "../../lib/errors";
import { clearModelChecks } from "./useModelCheck";

export function vertexChanged() {
  clearModelChecks();
  window.dispatchEvent(new Event("rt:vertex-changed"));
}

export function useVertexConnection(enabled: boolean) {
  const [connection, setConnection] = useState<VertexConnection | null>(null);
  const [models, setModels] = useState<VertexModel[]>([]);
  const [projects, setProjects] = useState<VertexProject[]>([]);
  const [detail, setDetail] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision((v) => v + 1);
    window.addEventListener("rt:vertex-changed", refresh);
    return () => window.removeEventListener("rt:vertex-changed", refresh);
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    setConnection(null);
    setDetail("");
    fetchVertexConnection()
      .then((state) => {
        if (live) setConnection(state);
      })
      .catch((err) => {
        if (live) setDetail(describe(err).detail);
      });
    fetchVertexModels()
      .then((data) => {
        if (live) setModels(data.models);
      })
      .catch(() => {
        if (live) setModels([]);
      });
    return () => {
      live = false;
    };
  }, [enabled, revision]);
  useEffect(() => {
    let live = true;
    setProjects([]);
    if (!enabled || !connection?.connected) return;
    async function load() {
      const all: VertexProject[] = [];
      let page = "";
      do {
        const data = await fetchVertexProjects(page);
        if (!live) return;
        all.push(...data.projects);
        page = data.next_page_token;
      } while (page);
      if (live) setProjects(all);
    }
    void load().catch(() => {
      if (live) setDetail("Project listing unavailable. Enter your project ID manually.");
    });
    return () => {
      live = false;
    };
  }, [enabled, connection?.connected, connection?.revision]);
  return { connection, models, projects, detail };
}
