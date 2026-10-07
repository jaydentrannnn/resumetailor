import { useEffect, useState } from "react";
import { fetchProfileOptions, type ProfileOptions } from "../api";

let cached: Promise<ProfileOptions> | null = null;

/** The fixed option lists (countries, states, self-ID answers), fetched once per page load. */
export function loadProfileOptions(): Promise<ProfileOptions> {
  cached ??= fetchProfileOptions().catch((reason) => {
    cached = null;
    throw reason;
  });
  return cached;
}

/** Option lists for the Profile pickers; null until they arrive (the pickers fall back to text). */
export function useProfileOptions(): ProfileOptions | null {
  const [options, setOptions] = useState<ProfileOptions | null>(null);
  useEffect(() => {
    let live = true;
    loadProfileOptions()
      .then((loaded) => {
        if (live) setOptions(loaded);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return options;
}

/** Visible text of the phone country picker ("United States (+1)"). */
export function phoneLabel(country: { name: string; dial: string }): string {
  return `${country.name} (${country.dial})`;
}
