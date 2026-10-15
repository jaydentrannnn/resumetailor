import { useState } from "react";
import type { Expansion } from "../api";
import { generateExpansion } from "../api";
import { describe } from "../lib/errors";
import { useToast } from "../lib/toast";
import { useConfirm } from "../state/confirmState";
import { Button } from "./ui";

/** Redraft a run's application experience (one model call), after a confirm. */
export function RegenerateExpansionButton({
  jobId,
  disabled = false,
  onRegenerated,
}: {
  jobId: string;
  disabled?: boolean;
  onRegenerated: (expansion: Expansion) => void;
}) {
  const { confirm } = useConfirm();
  const toast = useToast();
  const [working, setWorking] = useState(false);

  async function handleClick() {
    const ok = await confirm({
      title: "Regenerate application experience?",
      message: "This replaces the current text. The next fill uses the new version.",
      confirmLabel: "Regenerate",
    });
    if (!ok) return;
    setWorking(true);
    try {
      onRegenerated(await generateExpansion(jobId, { force: true }));
    } catch (err) {
      toast.error("Could not regenerate the experience", describe(err).detail);
    } finally {
      setWorking(false);
    }
  }

  return (
    <Button size="sm" disabled={disabled || working} onClick={() => void handleClick()}>
      {working ? "Regenerating…" : "Regenerate"}
    </Button>
  );
}
