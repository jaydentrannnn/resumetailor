import type { ApplicantProfile } from "../../api";

export type FieldValue = string | number | boolean | null;

/** What every profile field needs from the page: the draft, a setter, and its notes. */
export type FieldContext = {
  draft: ApplicantProfile;
  set: (key: keyof ApplicantProfile, value: FieldValue) => void;
  /** Problems to show now (touched fields, or every field after a Save attempt). */
  errors: Record<string, string>;
  /** Profile keys that forms ask for and the saved profile leaves blank. */
  gapFields: Set<string>;
  /** Server fallbacks used when a field is blank (`packet.DEFAULTS`). */
  defaults: Record<string, string>;
  passwordSet: boolean;
  touch: (key: string) => void;
};
