import { useCallback, useEffect, useRef } from "react";
import type { MasterResume } from "../../lib/resumeEdit";
import { undoKeyFor } from "../../lib/shortcuts";
import { useToast } from "../../lib/toast";
import {
  describeChange,
  emptyStack,
  record,
  redo as redoStep,
  structureKey,
  undo as undoStep,
} from "../../lib/undoStack";

type SetResume = (next: MasterResume | ((prev: MasterResume) => MasterResume)) => void;

/**
 * Undo / redo for the editor's structural edits. A change the editor makes through
 * `edit` that adds, removes or moves something is remembered (labelled by `pushUndo`
 * when the caller names it, otherwise by `describeChange`); a change from elsewhere
 * (import, restore from history, discard) clears the stack, since its steps no longer
 * describe this resume. The last step shows in the status bar with Undo / Redo, and
 * Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y) work outside text fields, which keep their own undo.
 */
export function useResumeUndo(resume: MasterResume | null, setResume: SetResume) {
  const toast = useToast();
  const stack = useRef(emptyStack<MasterResume>());
  const previous = useRef(resume);
  const source = useRef<"edit" | "restore" | null>(null);
  const labelled = useRef<MasterResume | null>(null);

  const step = useCallback(
    function step(direction: "undo" | "redo"): void {
      const current = previous.current;
      if (!current) return;
      const result =
        direction === "undo" ? undoStep(stack.current, current) : redoStep(stack.current, current);
      if (!result) return;
      stack.current = result.stack;
      source.current = "restore";
      setResume(result.step.snapshot);
      const back = direction === "undo" ? "redo" : "undo";
      toast.info(
        direction === "undo" ? `Undid: ${result.step.label}` : result.step.label,
        undefined,
        {
          label: back === "undo" ? "Undo" : "Redo",
          onClick: () => step(back),
        },
      );
    },
    [setResume, toast],
  );

  const remember = useCallback(
    (snapshot: MasterResume, label: string) => {
      stack.current = record(stack.current, snapshot, label);
      toast.info(label, undefined, { label: "Undo", onClick: () => step("undo") });
    },
    [toast, step],
  );

  useEffect(() => {
    const before = previous.current;
    const from = source.current;
    previous.current = resume;
    source.current = null;
    if (!before || !resume || before === resume || from === "restore") return;
    if (structureKey(before) === structureKey(resume)) return;
    if (from !== "edit") stack.current = emptyStack();
    else if (labelled.current === before) labelled.current = null;
    else remember(before, describeChange(before, resume));
  }, [resume, remember]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const action = undoKeyFor(event);
      if (!action) return;
      event.preventDefault();
      step(action);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [step]);

  return {
    /** The editor's own change: remembered for Undo when it alters the structure. */
    edit: useCallback<SetResume>(
      (next) => {
        source.current = "edit";
        setResume(next);
      },
      [setResume],
    ),
    /** Name the structural change about to be made (call it before making it). */
    pushUndo: useCallback(
      (label: string) => {
        if (!previous.current) return;
        labelled.current = previous.current;
        remember(previous.current, label);
      },
      [remember],
    ),
    /** Forget every step (after Discard). */
    clear: useCallback(() => {
      stack.current = emptyStack();
    }, []),
  };
}
