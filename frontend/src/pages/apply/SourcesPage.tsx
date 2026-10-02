import { Link } from "react-router-dom";
import { Page, PageHeader } from "../../components/ui";
import { useRunState } from "../../state/runState";
import { useSourcesStatus } from "./sourceHooks";
import { SourcesTab } from "./SourcesTab";

/**
 * Job sources: where the nightly run and Find jobs look for postings, per profile. Its own
 * page (opened from Apply settings or the Manage link beside Find jobs) because it is
 * setup, not part of working through the applications.
 */
export function SourcesPage() {
  const { settings, setSettings, settingsSaveError, settingsSaveState, flushSettings } =
    useRunState();
  const status = useSourcesStatus();
  return (
    <Page>
      <PageHeader
        title="Job sources"
        back={
          <Link to="/applications" className="text-sm text-accent underline">
            ← Applications
          </Link>
        }
      />
      <SourcesTab
        sources={settings.apply.sources}
        saveError={settingsSaveError}
        saveState={settingsSaveState}
        onFlush={flushSettings}
        status={status}
        fields={settings.apply.fields ?? []}
        onFieldsChange={(fields) =>
          setSettings({ ...settings, apply: { ...settings.apply, fields } })
        }
        onChange={(sources) => setSettings({ ...settings, apply: { ...settings.apply, sources } })}
      />
    </Page>
  );
}
