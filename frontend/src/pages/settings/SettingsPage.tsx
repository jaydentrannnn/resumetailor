import { useSearchParams } from "react-router-dom";
import { Tabs } from "../../components/ui";
import { AboutSection } from "./AboutSection";
import { AdvancedSection } from "./AdvancedSection";
import { DataSection } from "./DataSection";
import { DocumentsSection } from "./DocumentsSection";
import { ModelsSection } from "./ModelsSection";
import { BrowserSection } from "./BrowserSection";
import { TargetFieldSection } from "./TargetFieldSection";

const TABS = [
  { id: "models", label: "AI model" },
  { id: "documents", label: "Documents" },
  { id: "data", label: "Data" },
  { id: "advanced", label: "Advanced" },
  { id: "browser", label: "Browser" },
  { id: "about", label: "About" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/** App-wide settings. The tab lives in the URL (`?tab=`) so links can open one directly. */
export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === requested) ? (requested as TabId) : "models";
  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-bold text-ink">Settings</h1>
      <Tabs
        label="Settings sections"
        items={TABS.map((t) => ({ id: t.id, label: t.label }))}
        value={tab}
        onChange={(id) => setParams({ tab: id }, { replace: true })}
      />
      <div role="tabpanel">
        {tab === "models" && (
          <>
            <TargetFieldSection />
            <ModelsSection />
          </>
        )}
        {tab === "documents" && <DocumentsSection />}
        {tab === "data" && <DataSection />}
        {tab === "advanced" && <AdvancedSection />}
        {tab === "browser" && <BrowserSection />}
        {tab === "about" && <AboutSection />}
      </div>
    </div>
  );
}
