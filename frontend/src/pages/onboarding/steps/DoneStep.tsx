import { Button, StatusChip, Tile } from "../../../components/ui";
/** Step 6: all set. */
export function DoneStep({ onFinish, saving }: { onFinish: () => void; saving: boolean }) {
  return (
    <Tile aria-labelledby="step-title">
      <div className="space-y-3 py-4 text-center">
        <StatusChip tone="done">Setup complete</StatusChip>
        <h2 id="step-title" className="rt-tile-title">
          You're set up
        </h2>
        <p className="mx-auto max-w-md text-sm text-ink-muted">
          Paste a job posting on the Tailor page and get a resume matched to it, in your own design,
          in about a minute.
        </p>
        <Button variant="primary" size="lg" onClick={onFinish} loading={saving}>
          Tailor your first resume
        </Button>
      </div>
    </Tile>
  );
}
