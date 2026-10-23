import { useEffect, useState } from "react";
import { getMailProposals } from "../../api";
import { startAdaptivePoll } from "../../lib/adaptivePoll";

/** How many email updates wait to be accepted (the Tracker rail badge); null until known. */
export function usePendingEmailCount(): number | null {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    const poll = startAdaptivePoll(async () => {
      try {
        setCount((await getMailProposals()).proposals.length);
      } catch {
        // advisory: keep the last count
      }
      return false;
    });
    return () => poll.stop();
  }, []);
  return count;
}
