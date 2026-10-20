import { useSearchParams } from "react-router-dom";
import { CommandBar, Page, Tabs, TileLayout } from "../../components/ui";
import { WIDE, useMediaQuery } from "../../lib/useMediaQuery";
import { AboutSection } from "./AboutSection";
import { AiSection } from "./AiSection";
import { BrowserSection } from "./BrowserSection";
import { DataSection } from "./DataSection";

const TABS = [
  { id: "ai", label: "AI model" },
  { id: "data", label: "Data & backups" },
  { id: "browser", label: "Browser extension" },
  { id: "about", label: "About" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/** Tabs that were folded into others, so old links still land somewhere sensible. */
const MOVED: Record<string, TabId> = {
  models: "ai",
  advanced: "ai",
  documents: "about",
  appearance: "ai",
};

function tabFor(requested: string | null): TabId {
  if (requested && requested in MOVED) return MOVED[requested];
  return TABS.some((t) => t.id === requested) ? (requested as TabId) : "ai";
}

/**
 * App-wide settings: the sections in a column down the left, the open section's rows to
 * the right, filling the window (on wide screens the rows' label column grows too). The tab lives in the URL
 * (`?tab=`) so links can open one directly.
 */
export function SettingsPage() {
  const wide = useMediaQuery(WIDE);
  const [params, setParams] = useSearchParams();
  const tab = tabFor(params.get("tab"));
  return (
    <Page width="wide" className="lg:-mb-12 lg:-mt-5">
      <CommandBar title="Settings" />
      <div className="grid min-w-0 gap-6 lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-0">
        <div className="lg:-ml-2 lg:min-h-[calc(100vh-var(--rt-bar-top)-var(--rt-bar-bottom))] lg:border-r lg:border-line lg:py-5 lg:pr-3">
          <Tabs
            label="Settings sections"
            items={TABS.map((t) => ({ id: t.id, label: t.label }))}
            value={tab}
            orientation={wide ? "vertical" : "horizontal"}
            onChange={(id) => setParams({ tab: id }, { replace: true })}
          />
        </div>
        <div role="tabpanel" className="min-w-0 space-y-10 lg:py-5 lg:pb-12 lg:pl-10">
          <TileLayout.Provider value="flat">
            {tab === "ai" && <AiSection />}
            {tab === "data" && <DataSection />}
            {tab === "browser" && <BrowserSection />}
            {tab === "about" && <AboutSection />}
          </TileLayout.Provider>
        </div>
      </div>
    </Page>
  );
}
