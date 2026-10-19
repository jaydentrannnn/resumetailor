import { useEffect, useState } from "react";
import { listApplications } from "../../api";
import { startAdaptivePoll } from "../../lib/adaptivePoll";

/** How many applications wait on the person (the Apply rail badge); null until known. */
export function useNeedsYouCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    const poll = startAdaptivePoll(async () => {
      try {
        const page = await listApplications({ group: "review", archive: "active", limit: 1 });
        setCount(page.total);
      } catch {
        // advisory: keep the last count
      }
      return false;
    });
    return () => poll.stop();
  }, []);
  return count;
}
