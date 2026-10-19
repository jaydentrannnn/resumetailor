import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTemplateState } from "../../../state/templateState";
import { Button, CommandBar, Tabs } from "../../ui";
import { WIZARD_ANCHOR } from "../../../lib/useLayoutEditSession";
import { CoverLetterView } from "./CoverLetterView";
import { ResumeView } from "./ResumeView";

const VIEWS = [
  { id: "resume", label: "Resume" },
  { id: "cover", label: "Cover letter" },
];

/**
 * The Template page's command bar and workspace: switch between the resume and the
 * cover letter, each shown beside only the tools that apply to it. The view lives in the
 * URL (`?view=cover`) so reload keeps it. While Quick adjustments is open the switch is
 * hidden, so a draft can't be left behind by switching views.
 */
export function TemplateWorkspace() {
  const { info, loading, uploading, libraryBusy, previewRevision, pendingTemplate, refresh } =
    useTemplateState();
  const [params, setParams] = useSearchParams();
  const [adjusting, setAdjusting] = useState(false);
  const view = params.get("view") === "cover" ? "cover" : "resume";
  const installed = !!info?.tagged.exists;

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

  const bar = (
    <CommandBar
      title="Template"
      state={
        installed
          ? pendingTemplate
            ? `Switching to ${pendingTemplate}…`
            : info?.active_label
          : null
      }
      actions={
        <>
          {installed && !adjusting && (
            <Tabs
              variant="segmented"
              label="Template view"
              items={VIEWS}
              value={view}
              onChange={select}
            />
          )}
          <Button
            variant="plain"
            size="sm"
            onClick={() => void refresh()}
            disabled={loading || uploading || libraryBusy}
          >
            Refresh
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              document.getElementById(WIZARD_ANCHOR)?.scrollIntoView({ behavior: "smooth" })
            }
          >
            New template…
          </Button>
        </>
      }
    />
  );

  if (!installed)
    return (
      <>
        {bar}
        <p className="py-8 text-sm text-ink-muted">
          {loading
            ? "Loading template info…"
            : "No template yet. Pick a starter template below, or upload your own single-column Word file."}
        </p>
      </>
    );

  return (
    <>
      {bar}
      <section aria-label="Current template">
        {view === "cover" ? (
          <CoverLetterView reloadKey={previewRevision} />
        ) : (
          <ResumeView adjusting={adjusting} onAdjusting={setAdjusting} />
        )}
      </section>
    </>
  );
}
