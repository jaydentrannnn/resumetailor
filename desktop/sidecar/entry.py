"""PyInstaller entry script for the desktop sidecar (see `resumetailor.spec`)."""

from resume_tailor.desktop_main import main

if __name__ == "__main__":
    raise SystemExit(main())
