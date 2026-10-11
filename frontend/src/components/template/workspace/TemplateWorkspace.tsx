import { useSearchParams } from "react-router-dom";
import { useTemplateState } from "../../../state/templateState";
import { Tabs, Tile } from "../../ui";
import { CoverLetterView } from "./CoverLetterView";
import { ResumeView } from "./ResumeView";

const VIEWS = [
  { id: "resume", label: "Resume" },
  { id: "cover", label: "Cover letter" },
];

/**
 * The Template page's main tile: switch between the resume and the cover letter, each
 * shown beside only the tools that apply to it. The view lives in the URL (`?view=cover`)
 * so reload and Back keep it.
 */
export function TemplateWorkspace() {
  const { info, loading, previewRevision } = useTemplateState();
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "cover" ? "cover" : "resume";

  if (!info?.tagged.exists)
    return (
      <Tile aria-label="Current template">
        <p className="py-8 text-sm text-ink-muted">
          {loading
            ? "Loading template info…"
            : "No template yet. Pick a starter template below, or upload your own single-column Word file."}
        </p>
      </Tile>
    );

  const select = (id: string) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id === "cover") next.set("view", "cover");
        else next.delete("view");
        return next;
      },
      { replace: true },
    );

  return (
    <Tile aria-label="Current template">
      <div className="mb-5">
        <Tabs
          variant="segmented"
          label="Template view"
          items={VIEWS}
          value={view}
          onChange={select}
        />
      </div>
      <div role="tabpanel" aria-label={view === "cover" ? "Cover letter" : "Resume"}>
        {view === "cover" ? <CoverLetterView reloadKey={previewRevision} /> : <ResumeView />}
      </div>
    </Tile>
  );
}
