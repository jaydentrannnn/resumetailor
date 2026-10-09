import { Link, useSearchParams } from "react-router-dom";
import { DataList, Page, PageHeader, Tabs } from "../components/ui";
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
      <PageHeader
        title="Vocabulary"
        back={<Link to="/settings">← Settings</Link>}
        description="How skills are recognised across spellings. Used automatically on every run."
      />
      <DataList
        mono
        items={[
          { label: "Terms", value: effective.term_count },
          { label: "Spellings", value: effective.tag_alias_count },
          { label: "Opening verbs", value: effective.verb_count },
          { label: "Your additions", value: yours },
        ]}
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
      <div role="tabpanel" hidden={tab !== "dictionary"}>
        <DictionarySection />
      </div>
      <div role="tabpanel" hidden={tab !== "suggestions"}>
        <SuggestionsSection />
      </div>
    </Page>
  );
}
