---
name: apply-from-queue
description: Claude Desktop fallback for ResumeTailor postings stuck in needs_browser. Opens the posting URL, extracts JD text, starts tailor_application with metadata, then mark_application. Never fills or submits ATS forms — the deterministic Playwright filler does that.
---

# Apply from queue (needs_browser only)

Use when ResumeTailor's Applications tab shows postings with status `needs_browser`
(HTTP + CDP could not extract enough JD text).

## Prerequisites

- uvicorn / `docker compose` is running
- Claude Desktop MCP `resume-tailor` is configured
- Chrome MCP / DevTools available for opening pages

## Steps

1. `list_applications(status="needs_browser")`
2. For each row:
   - Open `posting_url` in the browser
   - Copy the visible job description text
   - Call `tailor_application(jd_text=..., posting_url=..., company=..., cover_letter=true)`
   - When the run succeeds, `mark_application(source_job_id, status="ready")` if the
     daily funnel did not already link the job — otherwise leave status to the app
3. Do **not** fill form fields or click Submit. Tell the user to open the Applications
   tab and use **Open & fill**.

## Out of scope

- Workday account login
- Auto-submit
- Editing `applicant_profile.json`
