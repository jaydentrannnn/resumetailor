import { useState } from "react";
import { calibrateTemplate } from "../api";
import { useTemplateState } from "../state/templateState";
import { describe } from "./errors";
import { useToast } from "./toast";

/** Measure the active template's line width and page length again, then refresh. */
export function usePageFitTune() {
  const { refresh } = useTemplateState();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string | null>(null);

  async function tune() {
    setRunning(true);
    try {
      const result = await calibrateTemplate();
      setLog([result.log, ...result.warnings.map((w) => `warning: ${w}`)].join("\n").trim());
      if (result.ok) toast.success("Page fit tuned for this template");
      else toast.error("Couldn't tune page fit", result.log.split("\n")[0]);
      await refresh();
    } catch (reason) {
      toast.error("Couldn't tune page fit", describe(reason).detail);
    } finally {
      setRunning(false);
    }
  }

  return { running, log, tune };
}
