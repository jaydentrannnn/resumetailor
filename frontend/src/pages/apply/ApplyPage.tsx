import { useCallback, useEffect, useRef, useState } from "react";
import { listApplications } from "../../api";
import { AttentionRow, ProfileGapsNotice } from "../../components/ProfileGapsNotice";
import { Button, Page, Skeleton } from "../../components/ui";
import { consumeApplicationListScroll } from "../../lib/applicationNavigation";
import { resolveApplyTab, type ApplyTab } from "../../lib/applyPage";
import { IN_FLIGHT_STATUSES } from "../../lib/applyPoll";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";
import { useOpenTabs } from "../../lib/useOpenTabs";
import { useProfileGaps } from "../../state/applicantProfileState";
import { useRunState } from "../../state/runState";
import { useWorkspaceState } from "../../state/workspaceState";
import { ApplicationsPanel } from "./ApplicationsPanel";
import { ApplyHeader } from "./ApplyHeader";
import { ApplySettingsDrawer } from "./ApplySettingsDrawer";
import { NightlyRunTile } from "./NightlyRunTile";
import { OperationBanner } from "./OperationBanner";
import { FindJobsTools, ProgressBulkActions, ProgressNote } from "./ProgressToolbar";
import { ReviewToolbar } from "./ReviewToolbar";
import { useSourcesStatus } from "./sourceHooks";
import { useApplicationTable, useApplyParams } from "./useApplicationTable";
import { useApplyOperation } from "./useApplyOperation";
import { useApplyRowActions } from "./useApplyRowActions";

/**
 * Apply: postings found for the student, split into Needs you / In progress / Done,
 * with the current Apply task pinned on top and every setting in a side drawer.
 */
export function ApplyPage() {
  const { settings, setSettings, config } = useRunState();
  const workspaceId = useWorkspaceState().activeId ?? "";
  const toast = useToast();
  const profileGaps = useProfileGaps();
  const { params, setParams, write, q, search, setQuery, setTab } = useApplyParams(workspaceId);
  const review = useApplicationTable("review", workspaceId, params, setParams, true, search);
  const queue = useApplicationTable("queue", workspaceId, params, setParams, true, search);
  const tab: ApplyTab = resolveApplyTab(params.get("tab"), review.data ? review.data.total : null);
  const tabDecided = params.has("tab") || review.data != null;
  const showDone = tab === "done" || search !== "";
  const archive = useApplicationTable("archive", workspaceId, params, setParams, showDone, search);
  const [archiveTotal, setArchiveTotal] = useState(0);
  const [revision, setRevision] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(params.get("settings") === "1");
  const { openTabs, reachable: tabsReachable, recheck: recheckTabs } = useOpenTabs();
  const showError = useCallback(
    (title: string, reason: unknown) => toast.error(title, describe(reason).detail),
    [toast],
  );

  const scrollRestored = useRef(false);
  useEffect(() => {
    if (scrollRestored.current || !queue.data) return;
    const position = consumeApplicationListScroll(workspaceId);
    if (position == null) return;
    scrollRestored.current = true;
    window.requestAnimationFrame(() => window.scrollTo(0, position));
  }, [workspaceId, queue.data]);

  const { refresh: refreshQueue } = queue;
  const { refresh: refreshArchive } = archive;
  const { refresh: refreshReview } = review;
  const refresh = useCallback(() => {
    refreshQueue();
    refreshReview();
    if (showDone) refreshArchive();
    recheckTabs();
    setRevision((n) => n + 1);
  }, [refreshQueue, refreshReview, refreshArchive, showDone, recheckTabs]);

  useEffect(() => {
    let live = true;
    listApplications({ archive: "archived", limit: 1 })
      .then((result) => live && setArchiveTotal(result.total))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [workspaceId, revision]);

  const op = useApplyOperation({
    workspaceId,
    refresh,
    inFlight: [queue.data, review.data].some((data) =>
      data?.applications.some((row) => IN_FLIGHT_STATUSES.has(row.status)),
    ),
    review: review.data,
    tabsReachable,
    showError,
  });
  const { active, browserConnected } = op;
  // Re-read each source's health whenever a run starts or finishes.
  const sourcesStatus = useSourcesStatus(active);
  const { busy, findOptions, setFindOptions, actions } = useApplyRowActions({
    apply: settings.apply,
    tables: [queue, review, archive],
    openTabs,
    active,
    browserConnected,
    workspaceId,
    refresh,
    setOperation: op.setOperation,
    wake: op.wake,
    showError,
  });
  const readyCount = (queue.data?.counts.ready ?? 0) + (review.data?.total ?? 0);
  const anySource = settings.apply.sources.some((source) => source.enabled);
  const flags = { busy, active, browserConnected };
  const find = () => actions.start("find");

  return (
    <Page width="wide">
      <ApplyHeader
        apply={settings.apply}
        browserConnected={browserConnected}
        onSettings={() => setDrawerOpen(true)}
      />
      {op.operation && <OperationBanner operation={op.operation} onControl={op.control} />}
      <ProfileGapsNotice gaps={profileGaps} />
      {!browserConnected && readyCount > 0 && (
        <AttentionRow
          label="Browser"
          action={
            <Button size="sm" onClick={() => setDrawerOpen(true)}>
              Set up
            </Button>
          }
          text={`Connect your browser to fill applications. ${readyCount} application${readyCount === 1 ? " is" : "s are"} ready or waiting on you.`}
        />
      )}
      <NightlyRunTile daily={op.daily} />
      {!tabDecided ? (
        <Skeleton className="h-48" />
      ) : (
        <ApplicationsPanel
          {...{ tab, q, search, review, queue, archive, archiveTotal, actions, anySource }}
          onTab={setTab}
          onQuery={setQuery}
          lastChecked={op.daily?.scheduler?.last_started_at}
          onFind={find}
          reviewBulk={
            <ReviewToolbar
              {...flags}
              selected={review.selectedRows}
              openTabs={openTabs}
              onContinue={(ids) => actions.start("fill", ids, "continue")}
              onReopen={actions.reopen}
            />
          }
          progress={{
            tools: (
              <FindJobsTools
                {...{ busy, active, anySource }}
                apply={settings.apply}
                options={findOptions}
                onOptions={setFindOptions}
                onFind={find}
              />
            ),
            bulk: (
              <ProgressBulkActions
                {...flags}
                selected={queue.selectedRows}
                onPrepare={(ids) => actions.start("prepare", ids)}
                onRetailor={actions.retailor}
                onFill={(ids) => actions.start("fill", ids)}
              />
            ),
            note: (
              <ProgressNote
                apply={settings.apply}
                sourcesStatus={sourcesStatus}
                selected={queue.selectedRows}
              />
            ),
          }}
        />
      )}
      {drawerOpen && (
        <ApplySettingsDrawer
          settings={settings}
          setSettings={setSettings}
          config={config}
          onClose={() => {
            setDrawerOpen(false);
            if (params.has("settings")) write((out) => out.delete("settings"));
          }}
          scheduler={op.daily?.scheduler ?? null}
          dailyRunning={op.dailyRunning}
          onRunNow={() => void op.runNow()}
          browserConnected={browserConnected}
          onCheckBrowser={op.checkBrowser}
          notify={op.notify}
        />
      )}
    </Page>
  );
}
