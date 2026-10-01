"""Application automation: discover, screen, packet, and fill ATS forms.

Deterministic orchestration. The only LLM calls are in ``answers/`` (``answer``,
``model_resolver``, ``hybrid_resolver``), exchanging plain strings with the model — never
document XML or markup. Subpackage map: ``CLAUDE.md`` beside this file.
Filling is driven by ``forms/filler.js`` injected into the user's host browser (Edge
recommended — see README) over CDP.
"""
