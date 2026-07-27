"""ResumeTailor — tailor a resume to a job description without touching its formatting.

The package is split so that the LLM never sees document structure:

- `jd` and `rewrite` call the Anthropic API and exchange only plain text and JSON.
- `render` is the only module that touches the `.docx`, and does so mechanically.

See CLAUDE.md for the full invariant.
"""

__version__ = "0.1.0"
