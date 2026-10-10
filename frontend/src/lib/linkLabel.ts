/**
 * Default label for a project link, named after the site it points to:
 * `github.com/me/repo` → "GitHub". A hosted app's own subdomain (`*.vercel.app`,
 * `*.github.io`, …) is "Live demo", not the host's brand.
 */

const KNOWN_HOSTS: Record<string, string> = {
  "github.com": "GitHub",
  "gitlab.com": "GitLab",
  "bitbucket.org": "Bitbucket",
  "devpost.com": "Devpost",
  "youtube.com": "YouTube",
  "youtu.be": "YouTube",
  "huggingface.co": "Hugging Face",
  "kaggle.com": "Kaggle",
  "figma.com": "Figma",
  "linkedin.com": "LinkedIn",
};

const HOSTING_SUFFIXES = [
  "github.io",
  "vercel.app",
  "netlify.app",
  "herokuapp.com",
  "pages.dev",
  "web.app",
  "firebaseapp.com",
  "onrender.com",
];

/** The legacy default every project row used to get, whatever its URL. */
export const LEGACY_LINK_LABEL = "Github";

export function labelForUrl(url: string): string {
  const raw = url.trim();
  if (!raw) return "";
  let host: string;
  try {
    host = new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`).hostname;
  } catch {
    return "";
  }
  host = host.toLowerCase().replace(/^www\./, "").replace(/\.$/, "");
  const parts = host.split(".");
  if (parts.length < 2 || parts.some((p) => !p)) return "";
  for (const [domain, label] of Object.entries(KNOWN_HOSTS)) {
    if (host === domain || host.endsWith(`.${domain}`)) return label;
  }
  if (HOSTING_SUFFIXES.some((s) => host.endsWith(`.${s}`))) return "Live demo";
  const name = parts[parts.length - 2];
  return name.charAt(0).toUpperCase() + name.slice(1);
}

/**
 * The label to keep after the URL changes from `oldUrl` to `newUrl`: re-derived while
 * the current label is still a default (empty, derived from the old URL, or the legacy
 * "Github"); anything the user typed themselves is kept.
 */
export function nextLinkLabel(label: string, oldUrl: string, newUrl: string): string {
  const current = label.trim();
  const isDefault =
    current === "" || current === labelForUrl(oldUrl) || current === LEGACY_LINK_LABEL;
  return isDefault ? labelForUrl(newUrl) : label;
}
