import { useState } from "react";
import { generateExpansion, regenerateCoverLetter } from "../../../api";
import { Button, Spinner, Tile } from "../../../components/ui";
import { describe } from "../../../lib/errors";
import { useConfirm } from "../../../state/confirmState";

/**
 * Generate or regenerate the two optional application extras for this row's run: the
 * experience descriptions (Prepare writes them only for sites whose fill pastes them)
 * and the cover letter. Each is one model call; the server rebuilds the packet so the
 * next fill uses the new text.
 */
export function ArtifactsCard({
  jobId,
  ready,
  hasExpansion,
  hasCover,
  expansionNeeded,
  onChanged,
}: {
  jobId: string;
  /** The run finished; the server refuses to generate from an unfinished one. */
  ready: boolean;
  hasExpansion: boolean;
  hasCover: boolean;
  expansionNeeded: boolean;
  onChanged: () => void;
}) {
  return (
    <Tile padding="sm">
      <h3 className="text-sm font-semibold text-ink">Application extras</h3>
      <div className="mt-2 divide-y divide-line">
        <ArtifactRow
          label="Experience descriptions"
          hint={
            expansionNeeded
              ? "Pasted into this site's role-description fields."
              : "This site doesn't use them. Generate only if the form asks for role descriptions."
          }
          exists={hasExpansion}
          ready={ready}
          run={(force) => generateExpansion(jobId, { force })}
          onDone={onChanged}
        />
        <ArtifactRow
          label="Cover letter"
          hint="Uploaded or pasted when the form asks for one."
          exists={hasCover}
          ready={ready}
          run={() => regenerateCoverLetter(jobId, "")}
          onDone={onChanged}
        />
      </div>
    </Tile>
  );
}

function ArtifactRow({
  label,
  hint,
  exists,
  ready,
  run,
  onDone,
}: {
  label: string;
  hint: string;
  exists: boolean;
  ready: boolean;
  run: (force: boolean) => Promise<unknown>;
  onDone: () => void;
}) {
  const { confirm } = useConfirm();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    if (exists) {
      const ok = await confirm({
        title: `Regenerate ${label.toLowerCase()}?`,
        message: "This replaces the current text. The next fill uses the new version.",
        confirmLabel: "Regenerate",
      });
      if (!ok) return;
    }
    setWorking(true);
    setError(null);
    try {
      await run(exists);
      onDone();
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setWorking(false);
    }
  }

  const action = exists ? "Regenerate" : "Generate";
  const progress = exists ? "Regenerating…" : "Generating…";
  return (
    <div className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">
          {label}
          <span className="font-normal text-ink-muted">
            {" "}
            · {exists ? "ready" : "not generated"}
          </span>
        </p>
        <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>
        {error && <p className="mt-1 text-xs text-danger">{error}</p>}
      </div>
      <Button
        size="sm"
        variant={exists ? "secondary" : "primary"}
        disabled={!ready || working}
        onClick={() => void handleClick()}
      >
        {working ? (
          <span className="inline-flex items-center gap-2">
            <Spinner /> {progress}
          </span>
        ) : (
          action
        )}
      </Button>
    </div>
  );
}
