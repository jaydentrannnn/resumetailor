# Tailoring measurements

CLI and web tailoring runs automatically write local measurements to the active
profile's `output/telemetry/<run-id>.json`. Failed and cancelled runs retain their
partial measurements. No prompt, resume text, job description, response body, API
key, or document markup is recorded. Saving measurements is best effort and cannot
fail a tailoring run.

From a source installation, summarize normal runs with:

```powershell
python -m resume_tailor.infra.usage_report --workspace <profile-id> --since 2026-10-05
python -m resume_tailor.infra.usage_report --workspace <profile-id> --json
```

Omit `--workspace` to use the active profile. Measurements start with this release;
old runs are not backfilled. Routing and behavior versions identify comparable
cohorts, and extraction cache hits are reported separately from cold runs.

The report includes logical model calls, physical HTTP attempts and retry reasons;
provider-reported input/output tokens and cache/reasoning subsets; cache hits,
misses and skips; median and p90 stage/operation, queue, request, resume-ready and
completion timings; and source-number omissions, successful repairs and source
fallbacks. Missing provider usage stays unknown. Cache and reasoning subsets are
not added to totals a second time. Concurrent timings overlap and must not be
summed to estimate wall time.

`artifact_usage.jsonl` records successful skills copies, downloads and supported
Apply autofill use by run ID. It contains no skills text. The consumption rate
counts successful web runs with a generated skills artifact and a complete
seven-day observation window, once per consuming run. Manual use outside these
actions and CLI consumption are unobserved; this is a partial signal.

JD voting and automatic skills generation remain unchanged. The report requests
a paired JD quality comparison after at least 30 successful comparable runs and
10 cold extractions. It suggests evaluating on-demand skills after at least 30
mature eligible runs with complete request usage, when observed consumption is
at most 20% and skills account for at least 10% of known tokens or completion
time beyond other concurrent stages. These gates prompt review; they never
change settings automatically. JD sample agreement alone does not prove resume
quality, so changing the vote requires a paired quality assessment.

Initial rewrites now restore dropped source numbers in the existing single
factual retry. A failed repair falls back to the original bullet with a run
warning. Entry ranking sums the best three bullet scores, limited by the
configured per-entry bullet cap, before applying the existing recency adjustment.
