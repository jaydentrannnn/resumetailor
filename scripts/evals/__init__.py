"""Model eval harness: replay saved postings through the real stage functions per arm.

Eval-only. Nothing under `src/` imports this package, so it never ships in the desktop
app. Entry point: `scripts/eval_models.py`. The judge (`judge.py`) and the hybrid
extractor (`hybrid_extract.py`) are the only callers here that reach a model directly,
and both exchange plain text/JSON only, never document content.
"""
