import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Page, PageHeader, Tabs } from "../../components/ui";
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
  const [wide, setWide] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const change = () => setWide(query.matches);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, []);
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab");
  const tab: TabId = TABS.some((t) => t.id === requested) ? (requested as TabId) : "models";
  return (
    <Page>
      <PageHeader
        title="Settings"
        eyebrow="On this computer"
        description="How ResumeTailor runs on this computer."
      />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[180px_minmax(0,1fr)] lg:gap-8">
        <Tabs
          label="Settings sections"
          items={TABS.map((t) => ({ id: t.id, label: t.label }))}
          value={tab}
          orientation={wide ? "vertical" : "horizontal"}
          onChange={(id) => setParams({ tab: id }, { replace: true })}
        />
        <div role="tabpanel" className="min-w-0 space-y-4">
          {tab === "models" && (
            <>
              <ModelsSection />
              <TargetFieldSection />
            </>
          )}
          {tab === "documents" && <DocumentsSection />}
          {tab === "data" && <DataSection />}
          {tab === "advanced" && <AdvancedSection />}
          {tab === "browser" && <BrowserSection />}
          {tab === "about" && <AboutSection />}
        </div>
      </div>
    </Page>
  );
}
