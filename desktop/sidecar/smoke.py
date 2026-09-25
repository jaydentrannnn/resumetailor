"""Smoke-test a built sidecar: it must print READY, serve /api/health, and exit with stdin.

    python desktop/sidecar/smoke.py desktop/sidecar/dist/resumetailor-server/resumetailor-server

Standard library only, so it runs before anything else is installed. Storage goes to a
throwaway folder, never the runner's real app-data folder.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path


def main(program: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "RESUME_TAILOR_LOG_DIR": "off"}
        for var in ("DATA", "TEMPLATES", "OUTPUT", "CACHE"):
            env[f"RESUME_TAILOR_{var}_DIR"] = str(Path(tmp) / var.lower())
        proc = subprocess.Popen(
            [program, "--exit-with-stdin"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        # A frozen build that never gets going must fail the job, not hang it.
        timer = threading.Timer(120, proc.kill)
        timer.start()
        try:
            assert proc.stdout is not None and proc.stdin is not None
            ready = next((line for line in proc.stdout if line.startswith("READY ")), "")
            if not ready:
                print("the sidecar exited without a READY line", file=sys.stderr)
                return 1
            _, port, _token = ready.split()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as r:
                if r.status != 200:
                    print(f"/api/health returned {r.status}", file=sys.stderr)
                    return 1
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
                if b'<div id="root"' not in r.read():
                    print("the web UI is not bundled", file=sys.stderr)
                    return 1
            proc.stdin.close()
            code = proc.wait(timeout=30)
            print(f"sidecar OK on port {port}; exited {code} after stdin closed")
            return code
        finally:
            timer.cancel()
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
