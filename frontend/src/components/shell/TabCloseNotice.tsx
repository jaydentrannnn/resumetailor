import { useEffect, useState } from "react";
import { getOpenTabs, keepApplicationTab, type ClosingTab } from "../../api";
import { startAdaptivePoll } from "../../lib/adaptivePoll";
import { describe } from "../../lib/errors";
import { TABS_CHANGED_EVENT } from "../../lib/tabsChanged";
import { useToast } from "../../lib/toast";

/**
 * A finished application's tab closes 30 s after it is submitted or skipped, unless the
 * applicant keeps it (`tab_close`). This shows each countdown on every page, with Keep open.
 */
export function TabCloseNotice() {
  const [closing, setClosing] = useState<ClosingTab[]>([]);
  const [seenAt, setSeenAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const toast = useToast();

  useEffect(() => {
    const poll = startAdaptivePoll(async () => {
      const result = await getOpenTabs();
      const items = result.closing ?? [];
      setClosing(items);
      setSeenAt(Date.now());
      return items.length > 0;
    });
    window.addEventListener(TABS_CHANGED_EVENT, poll.wake);
    return () => {
      window.removeEventListener(TABS_CHANGED_EVENT, poll.wake);
      poll.stop();
    };
  }, []);

  useEffect(() => {
    if (!closing.length) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [closing.length]);

  const keep = (tab: ClosingTab) => {
    setClosing((items) => items.filter((item) => item.id !== tab.id));
    keepApplicationTab(tab.id).catch((reason) => {
      const { title, detail } = describe(reason);
      toast.error(`Could not keep the ${tab.company || "application"} tab open: ${title}`, detail);
    });
  };

  if (!closing.length) return null;
  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-10 z-[55] flex flex-col items-end gap-2 sm:left-auto sm:w-96">
      {closing.map((tab) => {
        const left = Math.max(0, Math.ceil(tab.due_in - Math.max(0, now - seenAt) / 1000));
        return (
          <div
            key={tab.id}
            role="status"
            className="pointer-events-auto flex w-full items-center gap-3 rounded-sm bg-chrome px-3.5 py-3 text-[13px] text-ink shadow-lg"
          >
            <p className="min-w-0 flex-1">
              Closing the <span className="font-semibold">{tab.company || "application"}</span> tab
              in {left}s
            </p>
            <button
              type="button"
              className="rt-link shrink-0 font-semibold"
              onClick={() => keep(tab)}
            >
              Keep open
            </button>
          </div>
        );
      })}
    </div>
  );
}
