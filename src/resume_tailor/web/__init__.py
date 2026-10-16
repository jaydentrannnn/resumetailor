"""HTTP API and job queue for the ResumeTailor web UI.

The CLI (`tailor.py`) is unchanged: this package is an alternate front door onto the same
pipeline. Jobs run concurrently up to `max_concurrent_jobs` (see `jobs.py`); each runs in
its own `config.RunContext`, so per-run state never lives in a module global.
"""
