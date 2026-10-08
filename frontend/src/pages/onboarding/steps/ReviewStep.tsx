import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchSetupStatus, type SetupStatus } from "../../../api";
import { Button, DataList, TileSection } from "../../../components/ui";
import { reviewResume } from "../../../lib/onboarding";
import { useEditorState } from "../../../state/editorState";
/** Step 4: a summary of the imported content and anything worth fixing. */
export function ReviewStep() {
  const { resume, dirty, save, busy } = useEditorState();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    fetchSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  const review = reviewResume(resume);
  const fit = status?.items.find((i) => i.id === "calibration");
  const template = status?.items.find((i) => i.id === "template");

  return (
    <div className="space-y-4">
      {dirty && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-attn">
          <span>The imported content is not saved yet.</span>
          <Button variant="primary" size="sm" onClick={() => void save()} loading={busy}>
            Save it
          </Button>
        </div>
      )}
      <TileSection title="Your content">
        {review.entries === 0 ? (
          <p className="text-sm text-ink-muted">
            Nothing yet. Add your jobs, projects and activities in the{" "}
            <Link to="/profile/resume" className="font-semibold text-accent">
              resume editor
            </Link>
            ; tailoring picks from what you add there.
          </p>
        ) : (
          <>
            <DataList
              items={[
                { label: "Entries", value: review.entries },
                { label: "Bullet points", value: review.bullets },
                ...review.sections.map((section) => ({
                  label: section.title,
                  value: section.count,
                })),
              ]}
              mono
            />
          </>
        )}
        {review.warnings.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-attn">
            {review.warnings.slice(0, 8).map((w) => (
              <li key={w}>{w}</li>
            ))}
            {review.warnings.length > 8 && <li>…and {review.warnings.length - 8} more.</li>}
          </ul>
        )}
        <Link to="/profile/resume" className="rt-link mt-3 inline-block text-sm font-semibold">
          Open the resume editor
        </Link>
      </TileSection>
      {status && (
        <TileSection title="Template and page fit">
          <p className="text-sm text-ink">
            {template?.ok ? "Your template is installed." : "No template yet."}{" "}
            {fit?.ok
              ? "Page fit is measured for it."
              : "Page fit uses estimates until it is tuned on the Template page."}
          </p>
        </TileSection>
      )}
    </div>
  );
}
