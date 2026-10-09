import { useSearchParams } from "react-router-dom";
import { useEffect, useState } from "react";
import { Page, PageHeader, Tabs } from "../../components/ui";
import { AboutSection } from "./AboutSection";
import { AiSection } from "./AiSection";
import { BrowserSection } from "./BrowserSection";
import { DataSection } from "./DataSection";

const TABS = [
  { id: "ai", label: "AI" },
  { id: "data", label: "Data & backups" },
  { id: "browser", label: "Browser extension" },
  { id: "about", label: "About" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/** Tabs that were folded into others, so old links still land somewhere sensible. */
const MOVED: Record<string, TabId> = { models: "ai", advanced: "ai", documents: "about" };

function tabFor(requested: string | null): TabId {
  if (requested && requested in MOVED) return MOVED[requested];
  return TABS.some((t) => t.id === requested) ? (requested as TabId) : "ai";
}

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
  const tab = tabFor(params.get("tab"));
  return (
    <Page>
      <PageHeader
        title="Settings"
        description="AI, data and app preferences. Shared by every profile unless marked."
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
          {tab === "ai" && <AiSection />}
          {tab === "data" && <DataSection />}
          {tab === "browser" && <BrowserSection />}
          {tab === "about" && <AboutSection />}
        </div>
      </div>
    </Page>
  );
}
