import { Link, useSearchParams } from "react-router-dom";
import { CommandBar, Page, Tabs, TileLayout } from "../components/ui";
import { useLibraryState } from "../state/libraryState";
import { DictionarySection } from "./vocabulary/DictionarySection";
import { SuggestionsSection } from "./vocabulary/SuggestionsSection";

/**
 * Vocabulary: one always-on dictionary of skill spellings and opening verbs (built-in
 * plus the user's app-wide additions), and the suggestions drafted from this profile's
 * runs. Matching uses it automatically — nothing here needs setting up.
 */
export function VocabularyPage() {
  const { effective, entries, proposals } = useLibraryState();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "suggestions" ? "suggestions" : "dictionary";
  // A term you created through a spelling counts once, as that spelling.
  const yours = entries.reduce((n, e) => {
    const items = e.items.filter((i) => !i.builtin).length;
    return n + items + (!e.builtin && items === 0 ? 1 : 0);
  }, 0);
  return (
    <Page>
      <CommandBar
        title="Vocabulary"
        back={
          <Link to="/settings" className="hover:text-ink">
            ← Settings
          </Link>
        }
        state={
          <span className="font-mono text-xs">
            {effective.term_count} terms · {effective.tag_alias_count} spellings ·{" "}
            {effective.verb_count} opening verbs · {yours} yours
          </span>
        }
      />
      <Tabs
        variant="underline"
        label="Vocabulary sections"
        items={[
          { id: "dictionary", label: "Dictionary" },
          { id: "suggestions", label: "Suggestions", count: proposals.length },
        ]}
        value={tab}
        onChange={(value) => setParams({ tab: value })}
      />
      <TileLayout.Provider value="flat">
        <div role="tabpanel" hidden={tab !== "dictionary"}>
          <DictionarySection />
        </div>
        <div role="tabpanel" hidden={tab !== "suggestions"}>
          <SuggestionsSection />
        </div>
      </TileLayout.Provider>
    </Page>
  );
}
