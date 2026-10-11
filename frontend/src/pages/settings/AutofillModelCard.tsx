import { ModelSelectionCard, type ModelCardProps } from "./ModelSelectionCard";

export function AutofillModelCard(props: ModelCardProps) {
  return <ModelSelectionCard role="heavy" {...props} />;
}
