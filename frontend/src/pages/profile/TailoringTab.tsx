import { Link } from "react-router-dom";
import { Card } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { TargetFieldSection } from "./TargetFieldSection";

/**
 * Profile → Tailoring: the per-profile choices that steer every run. The target field
 * saves on its own, outside the profile save bar; skill vocabulary is app-wide and
 * automatic, so this only points at it.
 */
export function TailoringTab() {
  return (
    <div className="space-y-4">
      <TargetFieldSection />
      <Card
        title="Skill vocabulary"
        actions={
          <Link to="/vocabulary" className={buttonClass("secondary", "md")}>
            Open vocabulary
          </Link>
        }
      >
        <p className="text-sm text-ink-muted">
          Skills are recognised across spellings automatically (“Postgres” matches “PostgreSQL”).
          Add your own terms or spellings on the Vocabulary page.
        </p>
      </Card>
    </div>
  );
}
