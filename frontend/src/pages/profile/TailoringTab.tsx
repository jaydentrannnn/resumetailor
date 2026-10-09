import { Link } from "react-router-dom";
import { Card } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { TargetFieldSection } from "./TargetFieldSection";
import { VocabularyPacks } from "./VocabularyPacks";

/**
 * Profile → Tailoring: the per-profile choices that steer every run — the target field
 * and the skill vocabulary it brings. Both save on their own, outside the profile save bar.
 */
export function TailoringTab() {
  return (
    <div className="space-y-4">
      <TargetFieldSection />
      <Card
        title="Skill vocabulary"
        actions={
          <Link to="/vocabulary" className={buttonClass("secondary", "md")}>
            Edit packs
          </Link>
        }
      >
        <VocabularyPacks heading={false} />
      </Card>
    </div>
  );
}
