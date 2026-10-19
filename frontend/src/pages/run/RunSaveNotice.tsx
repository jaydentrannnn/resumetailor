import { useRunState } from "../../state/runState";

/** Under the Options title: whether the run options are saving, unsaved or failed. */
export function RunSaveNotice() {
  const { settingsLoaded, settingsSaveState, settingsSaveError, flushSettings } = useRunState();
  if (!settingsLoaded || settingsSaveState === "saved") return null;
  const failed = settingsSaveState === "failed";
  return (
    <p
      className={`mb-3 text-xs ${failed ? "text-danger" : "text-ink-muted"}`}
      role={failed ? "alert" : "status"}
    >
      {settingsSaveState === "saving"
        ? "Saving options…"
        : settingsSaveState === "unsaved"
          ? "Unsaved options"
          : `Options could not be saved: ${settingsSaveError ?? "Please retry."}`}
      {failed && (
        <button
          type="button"
          onClick={() => void flushSettings()}
          className="rt-link ml-2 font-medium"
        >
          Retry
        </button>
      )}
    </p>
  );
}
