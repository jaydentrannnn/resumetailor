import { useEffect, useState } from "react";
import { fetchSetupStatus, type SetupStatus } from "../../../api";
import { Button, StatusChip, Tile } from "../../../components/ui";

/** After the last step: applying is set up; where to go next. */
export function DoneStep({
  onFinish,
  onEdit,
  saving,
}: {
  /** Opens Apply when everything is ready (`true`), else the Tailor page. */
  onFinish: (ready: boolean) => void;
  onEdit: () => void;
  saving: boolean;
}) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  useEffect(() => {
    void fetchSetupStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);
  const ready = !!status?.ready;
  return (
    <Tile aria-labelledby="step-title">
      <div className="space-y-3 py-4 text-center">
        <StatusChip tone={ready ? "done" : "attention"}>Setup saved</StatusChip>
        <h2 id="step-title" tabIndex={-1} className="rt-tile-title">
          {ready ? "Ready to apply" : "Finish setting up when you're ready"}
        </h2>
        <p className="mx-auto max-w-md text-sm text-ink-muted">
          {ready
            ? "Open Apply and press Find jobs to search your job lists."
            : "Some features may still need setup. You can review your answers or explore the app."}
        </p>
        <Button variant="primary" size="lg" onClick={() => onFinish(ready)} loading={saving}>
          {ready ? "Find jobs" : "Open the app"}
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
