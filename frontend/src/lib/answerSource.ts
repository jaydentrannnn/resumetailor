/** Plain-language label for a filled field's `answer_source` in the review screens. */
const LABELS: Record<string, string> = {
  profile: "From your profile",
  resume: "From your resume",
  memory: "Answered from your saved answer",
  generated: "Drafted by the AI model",
  explicit_user_correction: "Your correction",
  existing_browser_answer: "Already on the form",
  required_consent: "Required consent box",
};

export function answerSourceLabel(source: string): string {
  return LABELS[source] ?? source.replaceAll("_", " ");
}
