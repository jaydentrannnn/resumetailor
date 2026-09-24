# Implementation Notes

The decision log ("why it was built this way") is split by topic under `docs/notes/`.
Each file is in log order; later entries supersede earlier ones; cross-check numbers
against the code.

**For agents — keep this cheap:**
- **Look things up by search, not by reading.** Grep `docs/notes/` for a keyword or a
  `^## ` heading, then Read only that entry (offset/limit). Never Read a topic file whole.
- **Add an entry by appending** to the matching topic file with a shell append
  (`>>` / `Add-Content`), never Read+Edit. Format: `## YYYY-MM-DD — title` then
  **What / Why / Impact**. If no topic fits, create `docs/notes/<topic>.md` and add a row
  below.

| File | Covers | Entries |
|---|---|---|
| [`fit-and-calibration.md`](notes/fit-and-calibration.md) | PDF measurement (Word/LibreOffice), calibration, underflow/overflow thresholds, SHORTEN_SCHEDULE, bullet shares, widow repair | 12 |
| [`llm-backends.md`](notes/llm-backends.md) | model profiles (ollama/lmstudio/gemini/claude), default models, token ceilings, timeouts, routing, cache-key origin | 13 |
| [`pipeline-and-guards.md`](notes/pipeline-and-guards.md) | rewrite prompts, fabrication/rebound-number guards, merge, polish, facets, skills stage, expansion, vocabulary packs, writing style, career-ops bands | 15 |
| [`template-and-render.md`](notes/template-and-render.md) | template build/tagging, header/bullet formatting, project links, hyperlinks in PDF, contact/name line, template tab & library, build verification, legacy build retirement | 15 |
| [`import-and-sections.md`](notes/import-and-sections.md) | arbitrary sections model, flexible template import, heading analyzer, wizard, content importer/merge, table layout | 9 |
| [`web-ui-and-mcp.md`](notes/web-ui-and-mcp.md) | SPA pages, job runner, Docker, downloads, settings, run history, theme, MCP server | 14 |
| [`cover-letter-and-claims.md`](notes/cover-letter-and-claims.md) | cover letter stage, its guard and template, Documents card, check_claims / verify-claim | 8 |
| [`apply-funnel.md`](notes/apply-funnel.md) | discovery sources, screening, packet, ATS hints, browser/filler, Workday/Greenhouse, daily run, Apply page | 21 |
| [`tooling-and-tests.md`](notes/tooling-and-tests.md) | repo hygiene, README, hermetic test suite | 3 |
