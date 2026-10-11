import { useCallback, useEffect, useState } from "react";
import {
  type CoverLetterField,
  type CoverLetterSettings,
  type CoverLetterSettingsResponse,
  fetchCoverLetterSettings,
  removeOwnLetter,
  saveCoverLetterSettings,
  uploadOwnLetter,
} from "../api";
import { describe } from "./errors";

/** The active profile's saved cover-letter settings and the lines its letterhead can show.
 * `reloadKey` refetches (a template switch changes the custom lines). */
export function useCoverLetterSettings(reloadKey: unknown) {
  const [settings, setSettings] = useState<CoverLetterSettings | null>(null);
  const [fields, setFields] = useState<CoverLetterField[]>([]);
  const [ownLetter, setOwnLetter] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((res: CoverLetterSettingsResponse) => {
    setSettings(res.settings);
    setFields(res.fields);
    setOwnLetter(Boolean(res.own_letter));
  }, []);

  useEffect(() => {
    let live = true;
    fetchCoverLetterSettings()
      .then((res) => {
        if (!live) return;
        apply(res);
        setError(null);
      })
      .catch((reason) => live && setError(describe(reason).detail));
    return () => {
      live = false;
    };
  }, [reloadKey, apply]);

  const save = useCallback(
    async (next: CoverLetterSettings) => apply(await saveCoverLetterSettings(next)),
    [apply],
  );

  /** Upload an own letter; its problems when it can't be used, else [] (and it is in use). */
  const uploadOwn = useCallback(
    async (file: File): Promise<string[]> => {
      const result = await uploadOwnLetter(file);
      if (!result.ok) return result.problems;
      apply(result.response);
      return [];
    },
    [apply],
  );

  const removeOwn = useCallback(async () => apply(await removeOwnLetter()), [apply]);

  return { settings, fields, ownLetter, error, save, uploadOwn, removeOwn };
}
