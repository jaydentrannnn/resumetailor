import { useCallback, useEffect, useState } from "react";
import { fetchSecrets, type SecretState } from "../../api";
import { describe } from "../../lib/errors";
import { useToast } from "../../lib/toast";

/** The stored API keys (names and whether each is set) and where they are kept. */
export function useSecrets() {
  const toast = useToast();
  const [secrets, setSecrets] = useState<SecretState[]>([]);
  const [storeBackend, setStoreBackend] = useState("");
  const reload = useCallback(() => {
    fetchSecrets()
      .then((res) => {
        setSecrets(res.secrets);
        setStoreBackend(res.backend);
      })
      .catch((err) => toast.error("Could not load API keys", describe(err).detail));
  }, [toast]);
  useEffect(reload, [reload]);
  return { secrets, storeBackend, reload };
}
