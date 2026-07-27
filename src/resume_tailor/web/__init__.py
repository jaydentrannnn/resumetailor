"""HTTP API and job queue for the ResumeTailor web UI.

The CLI (`tailor.py`) is unchanged: this package is an alternate front door onto the same
pipeline. Concurrency is deliberately serial — see `jobs.py` — because `config._ACTIVE`
is process-wide mutable state and a concurrent second model profile would race it.
"""
