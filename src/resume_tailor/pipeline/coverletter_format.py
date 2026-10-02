"""Plain-text formatting for the cover-letter prompt and its Markdown output (no LLM)."""

from __future__ import annotations

from datetime import date

from ..content.data import MasterResume
from . import coverletter_models


def _format_education(resume: MasterResume) -> str:
    """Format education entries for the cover-letter user message."""
    lines: list[str] = []
    for edu in resume.education:
        parts = [edu.school, edu.degree, edu.dates]
        if edu.gpa and edu.show_gpa:
            parts.append(f"GPA {edu.gpa}")
        lines.append(" | ".join(p for p in parts if p))
    return "\n".join(lines) or "(none)"

def _format_skills(resume: MasterResume) -> str:
    """Format skills groups for the cover-letter user message."""
    lines: list[str] = []
    for group in resume.skills:
        items = ", ".join(group.items)
        if items:
            lines.append(f"{group.label}: {items}")
    return "\n".join(lines) or "(none)"

def _format_tailored_entries(
    resume: MasterResume,
    bullets: dict[str, str],
) -> str:
    """Build the tailored-resume block for the cover-letter user message."""
    blocks: list[str] = []
    for section in resume.entry_sections:
        for entry in section.entries:
            entry_bullets = [
                (b.id, bullets[b.id])
                for b in entry.bullets
                if b.id in bullets
            ]
            if not entry_bullets:
                continue
            source_bullet = resume.bullet_by_id(entry_bullets[0][0])
            if hasattr(entry, "company"):
                label = f"{entry.title} at {entry.company}"
            else:
                label = getattr(entry, "name", section.title)
            bullet_lines = "\n".join(
                f"    <bullet id={bid!r}>\n"
                f"      <current>{text}</current>\n"
                f"      <permitted_skills>{', '.join((resume.bullet_by_id(bid) or source_bullet).tags)}</permitted_skills>\n"
                f"    </bullet>"
                for bid, text in entry_bullets
            )
            blocks.append(
                f"<entry>\n  <role>{label}</role>\n  <bullets>\n{bullet_lines}\n  </bullets>\n</entry>"
            )
    return "\n".join(blocks) or "(no tailored bullets)"

def _build_salutation(addressee: str) -> str:
    """Build the letter salutation from an optional named addressee."""
    if addressee.strip():
        return f"Dear {addressee.strip()},"
    return "Dear Hiring Manager,"

def _build_inside_address(company: str, company_location: str) -> list[str]:
    """Build the inside-address lines from validated posting fields."""
    lines: list[str] = []
    if company:
        lines.append(company)
    if company_location:
        lines.append(company_location)
    return lines

def _format_date_long(when: date | None = None) -> str:
    """Format a date as a long English month-day-year string."""
    when = when or date.today()
    return when.strftime("%B %d, %Y").replace(" 0", " ")

def format_markdown(letter: coverletter_models.CoverLetter) -> str:
    """Render the cover letter as plain text suitable for copy-all or a .md download."""
    lines: list[str] = []
    if letter.date:
        lines.append(letter.date)
        lines.append("")
    for line in letter.inside_address:
        lines.append(line)
    if letter.inside_address:
        lines.append("")
    lines.append(letter.salutation)
    lines.append("")
    lines.extend(letter.paragraphs)
    lines.append("")
    lines.append(letter.closing)
    lines.append(letter.signature)
    return "\n".join(lines)
