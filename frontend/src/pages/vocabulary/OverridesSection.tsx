import type { LibraryOverrides } from "../../api";
import { ChipListField } from "../../components/ChipListField";
import { KeyValueListField } from "../../components/KeyValueListField";
import { Tile } from "../../components/ui";
import { useLibraryState } from "../../state/libraryState";
import { buttonClass } from "../../lib/buttonClass";
export function OverridesSection() {
  const {
    overridesDraft: draft,
    overridesSaveState: saveState,
    editOverrides,
    flushOverrides,
  } = useLibraryState();

  function updateDraft(patch: Partial<LibraryOverrides>) {
    editOverrides(patch);
  }

  return (
    <Tile>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="rt-tile-title">Your additions</h2>
          <p className="mt-1 text-sm text-ink-muted">
            Per-profile edits layered on top of whichever packs are enabled above — these always win
            over a pack, and a removal always wins over an addition.
          </p>
        </div>
        {saveState !== "saved" && (
          <span className={`text-xs ${saveState === "failed" ? "text-danger" : "text-ink-muted"}`}>
            {saveState === "unsaved"
              ? "Unsaved…"
              : saveState === "saving"
                ? "Saving…"
                : "Save failed"}
          </span>
        )}
        {saveState === "failed" && (
          <button className={buttonClass("ghost", "sm")} onClick={() => void flushOverrides()}>
            Retry
          </button>
        )}
      </div>

      <fieldset className="mt-4 space-y-5">
        <KeyValueListField
          label="Added aliases (spelling → your canonical tag)"
          keyPlaceholder="e.g. pg"
          valuePlaceholder="e.g. postgresql"
          items={draft.tag_aliases}
          onChange={(next) => updateDraft({ tag_aliases: next })}
        />
        <ChipListField
          label="Removed aliases (suppress one from an enabled pack)"
          items={draft.tag_aliases_removed}
          onChange={(next) => updateDraft({ tag_aliases_removed: next })}
          placeholder="Type an alias key and press Enter"
        />
        <div>
          <KeyValueListField
            label="Added verb overrides (verb → family)"
            keyPlaceholder="e.g. triaged"
            valuePlaceholder="e.g. analyse"
            items={draft.verb_families}
            onChange={(next) => updateDraft({ verb_families: next })}
          />
          <p className="mt-1 text-xs text-ink-muted">
            One family per verb — the inverse of a pack's own family &rarr; verbs list.
          </p>
        </div>
        <ChipListField
          label="Removed verbs (suppress one from an enabled pack)"
          items={draft.verb_families_removed}
          onChange={(next) => updateDraft({ verb_families_removed: next })}
          placeholder="Type a verb and press Enter"
        />
      </fieldset>
    </Tile>
  );
}
