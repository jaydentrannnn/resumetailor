import { useEffect, useState } from "react";
import { fetchSetupStatus, type SetupStatus } from "../../../api";
import { Button, StatusChip, Tile } from "../../../components/ui";
/** Step 6: all set. */
export function DoneStep({
  onFinish,
  onEdit,
  saving,
}: {
  onFinish: () => void;
  onEdit: () => void;
  saving: boolean;
}) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    void fetchSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  return (
    <Tile aria-labelledby="step-title">
      <div className="space-y-3 py-4 text-center">
        <StatusChip tone={status?.ready ? "done" : "attention"}>Setup saved</StatusChip>
        <h2 id="step-title" tabIndex={-1} className="rt-tile-title">
          {status?.ready ? "Ready to tailor" : "Finish setting up when you're ready"}
        </h2>
        <p className="mx-auto max-w-md text-sm text-ink-muted">
          {status?.ready
            ? "Paste a job posting on the Tailor page to tailor your resume."
            : "Some features may still need setup. You can review your answers or explore the app."}
        </p>
        <Button variant="primary" size="lg" onClick={onFinish} loading={saving}>
          {status?.ready ? "Tailor your first resume" : "Open the app"}
        </Button>
        <Button onClick={onEdit} disabled={saving}>
          Review or edit setup
        </Button>
        {status && (
          <ul className="text-left text-sm">
            {status.items
              .filter((item) => !item.ok && !item.optional)
              .map((item) => (
                <li key={item.id}>
                  {item.label}: {item.detail}
                </li>
              ))}
          </ul>
        )}
      </div>
    </Tile>
  );
}
