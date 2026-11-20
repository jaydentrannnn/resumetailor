import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchSourceCatalog,
  getBrowserStatus,
  launchBrowser,
  type ApplySettings,
  type BrowserStatus,
  type SourceCatalog,
  type SourceField,
} from "../../../api";
import { Button, Card } from "../../../components/ui";
import { browserView } from "../../../lib/browserState";
import { describe } from "../../../lib/errors";
import {
  SKIP_WARNINGS,
  sourceFieldsForTarget,
  sourcesFromCatalogPicks,
  studyFieldForTarget,
  suggestedEntries,
  withSourceChoice,
} from "../../../lib/onboarding";
import { useRunState } from "../../../state/runState";
import { BrowserPicker, ConnectionStatus } from "../../apply/BrowserConnection";
import { StepFrame, type StepNav } from "../StepFrame";
import { JobSourcePicker } from "./JobSourcePicker";

/**
 * Stage 2: which job lists Find jobs searches (preselected from the target field) and
 * the browser Fill opens. The only requirement: when lists are offered, one stays on.
 */
export function ApplySetupStep({ nav }: { nav: StepNav }) {
  const { config, settings, setSettings, settingsLoaded, flushSettings } = useRunState();
  const target = config?.target_field ?? null;
  const apply = settings.apply;
  const [catalog, setCatalog] = useState<SourceCatalog | null>(null);
  // Until the student changes them, the job fields follow what was saved, else the target
  // field. Derived, not seeded once: the config can arrive after this step mounts.
  const [picked, setJobFields] = useState<SourceField[] | null>(null);
  const savedFields = apply.fields;
  const jobFields = useMemo(
    () => picked ?? (savedFields?.length ? savedFields : sourceFieldsForTarget(target)),
    [picked, savedFields, target],
  );
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const seeded = useRef(false);
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [catalogError, setCatalogError] = useState(false);
  const [browser, setBrowser] = useState<BrowserStatus | null>(null);
  const [launching, setLaunching] = useState(false);

  useEffect(() => {
    let live = true;
    setCatalogError(false);
    fetchSourceCatalog()
      .then((c) => live && setCatalog(c))
      .catch(() => live && setCatalogError(true));
    return () => {
      live = false;
    };
  }, [catalogAttempt]);

  useEffect(() => {
    getBrowserStatus()
      .then(setBrowser)
      .catch(() => undefined);
  }, []);

  // Coming back to this step: lists the student unticked before stay unticked.
  useEffect(() => {
    if (seeded.current || !catalog || !settingsLoaded) return;
    seeded.current = true;
    if (!apply.fields?.length) return;
    const have = new Set(apply.sources.map((s) => s.catalog_id));
    setSkipped(
      new Set(
        suggestedEntries(catalog, jobFields, target)
          .filter((e) => !have.has(e.id))
          .map((e) => e.id),
      ),
    );
  }, [catalog, settingsLoaded, apply, jobFields, target]);

  const suggestions = catalog ? suggestedEntries(catalog, jobFields, target) : [];

  /** The settings with this step's job lists written in (unchanged without a field). */
  function withJobLists(): ApplySettings {
    if (!catalog || !target) return apply;
    const sources = sourcesFromCatalogPicks(
      apply.sources,
      suggestions.filter((entry) => !skipped.has(entry.id)),
      studyFieldForTarget(target),
    );
    return withSourceChoice(apply, sources, jobFields);
  }

  async function save(): Promise<boolean> {
    setError(null);
    const next = withJobLists();
    if (next !== apply) setSettings({ ...settings, apply: next });
    if (await flushSettings()) return true;
    setError("Could not save your job lists. Try again.");
    return false;
  }

  async function launch() {
    setLaunching(true);
    try {
      if (!(await flushSettings())) throw new Error("Could not save browser settings.");
      setBrowser(await launchBrowser());
    } catch (err) {
      setError(describe(err).detail);
    } finally {
      setLaunching(false);
    }
  }

  const view = browserView(browser, apply.browser ?? null);
  // With lists on offer and every one unticked, Find jobs would have nothing of the
  // student's to search: Next waits for one list (Skip still leaves the step, with its
  // warning). No field, or a failed catalog, offers nothing to tick and never blocks.
  const noListOn =
    !!target && suggestions.length > 0 && suggestions.every((entry) => skipped.has(entry.id));
  return (
    <StepFrame
      title="Job lists and browser"
      intro="Which job lists Find jobs searches, and the browser that opens to fill in applications. Both can be changed later on the Apply page."
      nav={nav}
      complete={!noListOn}
      onSave={save}
      skipWarning={SKIP_WARNINGS.apply_tools}
      error={error}
    >
      {catalogError && (
        <div role="alert">
          Could not load job lists.{" "}
          <Button onClick={() => setCatalogAttempt((n) => n + 1)}>Retry job lists</Button> You can
          skip and choose lists later.
        </div>
      )}
      {!catalog && !catalogError && (
        <p role="status" className="border-t border-line pt-4 text-sm text-ink-muted">
          Loading job lists…
        </p>
      )}
      {catalog &&
        (target ? (
          <JobSourcePicker
            fields={jobFields}
            onFields={setJobFields}
            suggestions={suggestions}
            skipped={skipped}
            onToggle={(id) =>
              setSkipped((prev) => {
                const next = new Set(prev);
                if (!next.delete(id)) next.add(id);
                return next;
              })
            }
          />
        ) : (
          <p className="border-t border-line pt-4 text-sm text-ink-muted">
            Job lists are suggested from your target field. Choose one on the Your field step, or
            add lists later on the Apply page.
          </p>
        ))}
      {noListOn && (
        <p role="status" className="text-sm text-attn">
          Tick at least one job list so Find jobs has somewhere to look, or press Skip.
        </p>
      )}
      <Card
        embedded
        className="border-t border-line pt-4"
        title="Browser"
        description="The browser autofill opens to fill in applications."
        actions={<ConnectionStatus view={view} />}
      >
        <BrowserPicker
          status={browser}
          view={view}
          selected={apply.browser ?? null}
          onSelect={(id) => setSettings({ ...settings, apply: { ...apply, browser: id } })}
          launch={{ run: () => void launch(), busy: launching }}
        />
      </Card>
    </StepFrame>
  );
}
