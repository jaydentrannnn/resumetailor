import { useCallback, useEffect, useState } from "react";
import {
  type CoverLetterField,
  type CoverLetterSettings,
  fetchCoverLetterSettings,
  saveCoverLetterSettings,
} from "../api";
import { describe } from "./errors";

/** The active profile's saved cover-letter settings and the lines its letterhead can show.
 * `reloadKey` refetches (a template switch changes the custom lines). */
export function useCoverLetterSettings(reloadKey: unknown) {
  const [settings, setSettings] = useState<CoverLetterSettings | null>(null);
  const [fields, setFields] = useState<CoverLetterField[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchCoverLetterSettings()
      .then((res) => {
        if (!live) return;
        setSettings(res.settings);
        setFields(res.fields);
        setError(null);
      })
      .catch((reason) => live && setError(describe(reason).detail));
    return () => {
      live = false;
    };
  }, [reloadKey]);

  const save = useCallback(async (next: CoverLetterSettings) => {
    const res = await saveCoverLetterSettings(next);
    setSettings(res.settings);
    setFields(res.fields);
  }, []);

  return { settings, fields, error, save };
}
