/** Word count of a pasted posting, for the "1,240 words" hint under the text box. */
export function wordCount(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

/** Host shown in "Fetched from boards.greenhouse.io", without a leading "www.". */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export const JD_FILE_ACCEPT = ".txt,.md,.pdf,.docx,.html,.htm";
