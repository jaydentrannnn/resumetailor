import type { ApplicantProfile } from "../api";
import type { MasterResume } from "./resumeEdit";
import { validateProfile } from "./profileForm";

export function realContact(value: string | undefined): string {
  const text = value?.trim() ?? "";
  return ["your name", "your", "name", "you@example.com"].includes(text.toLowerCase()) ? "" : text;
}

export function contactErrors(contact: MasterResume["contact"] | null | undefined) {
  if (!contact) return {};
  const errors = validateProfile({
    email: realContact(contact.email),
    phone: contact.phone ?? "",
    linkedin_url: contact.linkedin ?? "",
    github_url: contact.github ?? "",
  } as ApplicantProfile);
  return Object.fromEntries(
    Object.entries(errors)
      .filter(([key]) => ["email", "phone", "linkedin_url", "github_url"].includes(key))
      .map(([key, value]) => [key.replace("_url", ""), value]),
  );
}
