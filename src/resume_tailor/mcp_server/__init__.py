"""MCP front door for ResumeTailor: thin HTTP client over the existing web API.

Claude Desktop (or any MCP host) talks stdio JSON-RPC to this package; the package
calls the running uvicorn server at ``RESUME_TAILOR_API`` (default
``http://127.0.0.1:8000``). It never owns ``config._ACTIVE`` or starts uvicorn —
the web process remains the sole pipeline owner.
"""
