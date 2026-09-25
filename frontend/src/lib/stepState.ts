export type StepState = "done" | "current" | "upcoming" | "error";

/** State of step ``index`` given the current step and an optional failed one. */
export function stepState(index: number, current: number, failed?: number | null): StepState {
  if (failed != null && index === failed) return "error";
  if (index < current) return "done";
  if (index === current) return "current";
  return "upcoming";
}
