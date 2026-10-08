import { useEffect, useState } from "react";
import { SECTION_KIND_LABELS, type Section } from "../../lib/resumeEdit";

/** Tracks the section in view without changing the editor's draft or navigation. */
export function SectionIndex({ sections }: { sections: Section[] }) {
  const [active, setActive] = useState(sections[0]?.id ?? "");
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.find((entry) => entry.isIntersecting);
        if (visible) setActive(visible.target.id.replace("resume-section-", ""));
      },
      { rootMargin: "-10% 0px -65% 0px" },
    );
    sections.forEach((section) => {
      const element = document.getElementById(`resume-section-${section.id}`);
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, [sections]);

  return (
    <>
      <label className="mb-3 block text-sm lg:hidden">
        Jump to section
        <select
          className="field mt-1"
          defaultValue=""
          onChange={(event) => {
            setActive(event.target.value);
            document
              .getElementById(`resume-section-${event.target.value}`)
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          <option value="" disabled>
            Choose a section
          </option>
          {sections.map((section) => (
            <option key={section.id} value={section.id}>
              {section.title || SECTION_KIND_LABELS[section.kind]}
            </option>
          ))}
        </select>
      </label>
      <nav aria-label="Resume sections" className="sticky top-4 hidden space-y-1 lg:block">
        <p className="rt-eyebrow mb-3 px-3">Sections</p>
        {sections.map((section) => (
          <a
            key={section.id}
            href={`#resume-section-${section.id}`}
            aria-current={active === section.id ? "location" : undefined}
            onClick={() => setActive(section.id)}
            className={`flex items-center justify-between gap-3 rounded-sm border-l-2 px-3 py-2 text-sm ${active === section.id ? "border-accent bg-sunken text-ink" : "border-transparent text-ink-muted hover:bg-sunken hover:text-ink"}`}
          >
            <span className="min-w-0 break-words">
              {section.title || SECTION_KIND_LABELS[section.kind]}
            </span>
            <span className="font-mono text-xs text-ink-muted">{section.entries.length}</span>
          </a>
        ))}
      </nav>
    </>
  );
}
