"""The blind judge's verdicts from the Codex CLI instead of an API endpoint (eval-only).

`judge.run(..., asker=codex_asker(model, effort))` sends each judgement to one fresh,
ephemeral `codex exec` session on the user's Codex sign-in, so no API key is spent and
the two orders of a pair never share a context (`judge.both_orders` only means anything
when they don't). The session runs in an empty folder with the user's Codex config
ignored (no MCP servers, hooks or project instructions leak into the verdict), a
read-only sandbox, and a JSON schema for the reply. Plain text in, a small JSON verdict
out, as with every judge here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .judge import Verdict, system

#: The reply shape `codex exec --output-schema` enforces (same as `judge.Verdict`).
SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["A", "B", "tie"]},
        "reason": {"type": "string"},
    },
    "required": ["winner", "reason"],
    "additionalProperties": False,
}
_PREAMBLE = (
    "You are a blind judge in an evaluation. Answer from the text below alone: do not run "
    "commands, read files or browse. Reply with the JSON verdict only.\n\n"
)
TIMEOUT_S = 600


def executable() -> str:
    found = shutil.which("codex")
    if found is None:
        raise RuntimeError("the codex CLI is not on PATH")
    return found


def command(model: str, effort: str, workdir: Path, schema: Path, out: Path) -> list[str]:
    return [
        executable(), "exec", "-m", model, "-c", f'model_reasoning_effort="{effort}"',
        "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
        "-s", "read-only", "-C", str(workdir), "--color", "never",
        "--output-schema", str(schema), "-o", str(out), "-",
    ]


def parse(text: str) -> Verdict:
    """The verdict from Codex's last message (bare JSON, or JSON inside a code fence)."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`").removeprefix("json").strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"codex returned no JSON verdict: {text[:200]!r}")
    return Verdict.model_validate(json.loads(body[start:end + 1]))


def codex_asker(model: str, effort: str = "medium",
                runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
                ) -> Callable[[str, str], Verdict]:
    """An `asker` for `judge.run`/`judge.both_orders` backed by `codex exec`."""

    def ask(user: str, stage: str) -> Verdict:
        with tempfile.TemporaryDirectory(prefix="codex-judge-") as tmp:
            workdir = Path(tmp) / "empty"
            workdir.mkdir()
            schema, out = Path(tmp) / "schema.json", Path(tmp) / "verdict.json"
            schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
            prompt = _PREAMBLE + system(stage) + "\n\n" + user
            done = runner(command(model, effort, workdir, schema, out), input=prompt,
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=TIMEOUT_S, env={**os.environ, "NO_COLOR": "1"})
            if done.returncode != 0:
                tail = (done.stderr or done.stdout or "").strip()[-300:]
                raise RuntimeError(f"codex exec exited {done.returncode}: {tail}")
            if not out.exists():
                raise RuntimeError("codex exec wrote no final message")
            return parse(out.read_text(encoding="utf-8"))

    return ask
