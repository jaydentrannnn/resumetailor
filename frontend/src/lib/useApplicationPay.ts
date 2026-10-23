import { useEffect, useState } from "react";
import { getApplicationPay, type ApplicationPay } from "../api";

/** The posting's own range and posted ranges for similar roles, or null while loading. */
export function useApplicationPay(sourceJobId: string): ApplicationPay | null {
  const [pay, setPay] = useState<ApplicationPay | null>(null);
  useEffect(() => {
    let live = true;
    getApplicationPay(sourceJobId)
      .then((result) => live && setPay(result))
      .catch(() => live && setPay(null));
    return () => {
      live = false;
    };
  }, [sourceJobId]);
  return pay;
}
