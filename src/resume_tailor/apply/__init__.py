"""Application automation: discover, screen, packet, and fill ATS forms.

Deterministic orchestration. The only LLM call in this package is ``answer.py``,
and it exchanges plain strings with the model — never document XML or markup.
Filling is driven by ``filler.js`` injected into the user's host browser (Edge
recommended — see README) over CDP.
"""
