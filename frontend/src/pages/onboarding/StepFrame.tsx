import type { ReactNode } from "react";
import { Button, Tile } from "../../components/ui";

export function StepFrame({
  title,
  intro,
  children,
  onBack,
  onNext,
  nextLabel = "Next",
  saving,
}: {
  title: string;
  intro: string;
  children: ReactNode;
  onBack?: () => void;
  onNext?: () => void;
  nextLabel?: string;
  saving: boolean;
}) {
  return (
    <Tile aria-labelledby="step-title" className="space-y-4">
      <div>
        <h2 id="step-title" className="rt-tile-title">
          {title}
        </h2>
        <p className="mt-1 text-sm text-ink-muted">{intro}</p>
      </div>
      {children}
      {(onBack || onNext) && (
        <div className="flex flex-wrap justify-between gap-3 border-t border-line pt-4">
          {onBack ? (
            <Button variant="ghost" onClick={onBack} disabled={saving}>
              Back
            </Button>
          ) : (
            <span />
          )}
          {onNext && (
            <Button variant="primary" onClick={onNext} loading={saving}>
              {nextLabel}
            </Button>
          )}
        </div>
      )}
    </Tile>
  );
}
