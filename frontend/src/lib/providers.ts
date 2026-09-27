/** Plain-language descriptions of the model profiles a student chooses between. */
export interface ProviderInfo {
  id: string;
  name: string;
  summary: string;
  /** API key names that satisfy this provider (any one), empty for local servers. */
  keys: string[];
  local: boolean;
  /** Where to get a key or the app. */
  link?: { label: string; href: string };
}

export const PROVIDERS: ProviderInfo[] = [
  {
    id: "ollama",
    name: "Ollama",
    summary:
      "Free. Uses the Ollama app on this computer (run `ollama signin` for cloud models). Needs Ollama installed.",
    keys: [],
    local: true,
    link: { label: "Get Ollama", href: "https://ollama.com/download" },
  },
  {
    id: "ollama-cloud",
    name: "Ollama Cloud",
    summary:
      "Runs on Ollama's servers with your Ollama account, so there is nothing to install. Needs an Ollama API key.",
    keys: ["OLLAMA_API_KEY", "LLM_API_KEY"],
    local: false,
    link: { label: "Get an API key", href: "https://ollama.com/settings/keys" },
  },
  {
    id: "claude",
    name: "Anthropic Claude",
    summary: "Best writing quality. You pay Anthropic per run (usually a few cents).",
    keys: ["ANTHROPIC_API_KEY"],
    local: false,
    link: { label: "Get an API key", href: "https://console.anthropic.com/settings/keys" },
  },
  {
    id: "gemini",
    name: "Google Gemini",
    summary: "Good quality with a free tier. Needs a Google AI Studio key.",
    keys: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    local: false,
    link: { label: "Get an API key", href: "https://aistudio.google.com/apikey" },
  },
  {
    id: "lmstudio",
    name: "LM Studio",
    summary: "Free. Runs a model you load in LM Studio on this computer.",
    keys: [],
    local: true,
    link: { label: "Get LM Studio", href: "https://lmstudio.ai" },
  },
];

export function providerInfo(id: string): ProviderInfo | undefined {
  return PROVIDERS.find((p) => p.id === id);
}

/** Readable names for the savable key slots. */
export const KEY_LABELS: Record<string, string> = {
  ADZUNA_APP_ID: "Adzuna App ID (job search)",
  ADZUNA_APP_KEY: "Adzuna App Key (job search)",
  ANTHROPIC_API_KEY: "Anthropic API key",
  GEMINI_API_KEY: "Gemini API key",
  GOOGLE_API_KEY: "Google API key (alternative to the Gemini key)",
  LLM_API_KEY: "Custom server key (OpenAI-compatible)",
  OLLAMA_API_KEY: "Ollama cloud key (only for Ollama cloud models)",
  USAJOBS_API_KEY: "USAJobs API Key (job search)",
  USAJOBS_EMAIL: "USAJobs Email (User-Agent header)",
};

/** Help text and links for savable credentials. */
export const KEY_HELP: Record<string, { label: string; href: string }> = {
  ADZUNA_APP_ID: { label: "developer.adzuna.com", href: "https://developer.adzuna.com/" },
  ADZUNA_APP_KEY: { label: "developer.adzuna.com", href: "https://developer.adzuna.com/" },
  USAJOBS_API_KEY: { label: "developer.usajobs.gov", href: "https://developer.usajobs.gov/APIRequest/Index" },
  USAJOBS_EMAIL: { label: "developer.usajobs.gov", href: "https://developer.usajobs.gov/APIRequest/Index" },
};
