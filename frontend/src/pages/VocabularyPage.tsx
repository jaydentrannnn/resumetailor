import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";
import { DataList, Page, PageHeader, Tabs } from "../components/ui";
import { useLibraryState } from "../state/libraryState";
import { PacksSection } from "./vocabulary/PacksSection";
import { OverridesSection } from "./vocabulary/OverridesSection";
import { SuggestionsSection } from "./vocabulary/SuggestionsSection";
/**
 * Vocabulary tab: manage the tag-alias and verb-family vocabulary that JD matching and
 * opening-verb variety checking draw on. Three layers, composed top to bottom: Packs
 * (which built-in/user-authored bundles are active, and in what order), Your additions
 * (per-profile overrides that always win over a pack), and Suggestions (LLM-drafted
 * additions awaiting approval into a pack, i.e. feeding back into layer one).
 */
export function VocabularyPage() {
  const { effective, packs, enabledPacks, overridesDraft, proposals } = useLibraryState();
  const [params, setParams] = useSearchParams();
  const tab = ["packs", "additions", "suggestions"].includes(params.get("tab") ?? "")
    ? params.get("tab")!
    : "packs";
  return (
    <Page>
      <PageHeader
        title="Vocabulary"
        eyebrow="Writing vocabulary"
        back={<Link to="/settings">← Settings</Link>}
        description="The words the rewriter may use. Packs add verbs and terms for a field; additions are yours."
      />
      <DataList
        mono
        items={[
          { label: "Packs on", value: `${enabledPacks.length} of ${packs.length}` },
          {
            label: "Your additions",
            value:
              Object.keys(overridesDraft.tag_aliases).length +
              Object.keys(overridesDraft.verb_families).length,
          },
          { label: "Suggestions", value: proposals.length },
          {
            label: "Active vocabulary",
            value: `${effective.tag_alias_count} aliases · ${effective.verb_count} verbs`,
          },
        ]}
      />
      <Tabs
        variant="segmented"
        label="Vocabulary sections"
        items={[
          { id: "packs", label: "Packs" },
          { id: "additions", label: "Additions" },
          { id: "suggestions", label: "Suggestions" },
        ]}
        value={tab}
        onChange={(value) => setParams({ tab: value })}
      />
      <div role="tabpanel" hidden={tab !== "packs"}>
        <PacksSection />
      </div>
      <div role="tabpanel" hidden={tab !== "additions"}>
        <OverridesSection />
      </div>
      <div role="tabpanel" hidden={tab !== "suggestions"}>
        <SuggestionsSection />
      </div>
    </Page>
  );
}
