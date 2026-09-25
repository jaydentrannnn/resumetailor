import { useEffect, useState } from "react";
import { fetchHealth } from "../../api";
import { Card, Kbd } from "../../components/ui";
import { buttonClass } from "../../lib/buttonClass";
import { SHORTCUTS } from "../../lib/shortcuts";

/** Settings → About: version, diagnostics for support, shortcuts. */
export function AboutSection() {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    fetchHealth()
      .then((h) => setVersion(h.version))
      .catch(() => setVersion(null));
  }, []);
  return (
    <div className="space-y-6">
      <Card title="ResumeTailor" description={version ? `Version ${version}` : undefined}>
        <p className="text-sm text-ink">
          Tailors your resume to each job without changing its look, and never adds anything you did
          not write.
        </p>
      </Card>
      <Card
        title="Get help"
        description="The diagnostics file shows what the app did, with your name, contact details, keys and passwords removed. Attach it when you report a problem."
      >
        <a className={buttonClass("secondary")} href="/api/diagnostics.zip" download>
          Download diagnostics
        </a>
      </Card>
      <Card title="Keyboard shortcuts">
        <ul className="space-y-2 text-sm">
          {SHORTCUTS.map((s) => (
            <li key={s.action} className="flex items-center justify-between gap-4">
              <span>{s.description}</span>
              <span className="flex gap-1">
                {s.keys.map((k) => (
                  <Kbd key={k}>{k}</Kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
