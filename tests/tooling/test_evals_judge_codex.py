"""Codex CLI judge (`scripts/evals/judge_codex.py`): the command, the prompt, the reply.

`subprocess.run` is replaced by a hand-written runner; nothing here starts Codex.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evals import judge, judge_codex  # noqa: E402


class _Runner:
    """Records each call and writes `reply` where `-o` points, like `codex exec`."""

    def __init__(self, reply: str | None, returncode: int = 0):
        self.reply, self.returncode, self.calls = reply, returncode, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.reply is not None:
            Path(argv[argv.index("-o") + 1]).write_text(self.reply, encoding="utf-8")
        return subprocess.CompletedProcess(argv, self.returncode, "", "boom")


@pytest.fixture(autouse=True)
def _codex_on_path(monkeypatch):
    monkeypatch.setattr(judge_codex, "executable", lambda: "codex")


def test_each_judgement_is_one_isolated_ephemeral_session():
    runner = _Runner(json.dumps({"winner": "B", "reason": "B is faithful."}))
    ask = judge_codex.codex_asker("gpt-6.1-sol", "medium", runner=runner)

    verdict = ask("<A>x</A><B>y</B>", "rewrite")

    assert verdict == judge.Verdict(winner="B", reason="B is faithful.")
    argv, kwargs = runner.calls[0]
    assert argv[:4] == ["codex", "exec", "-m", "gpt-6.1-sol"]
    assert 'model_reasoning_effort="medium"' in argv
    for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--output-schema"):
        assert flag in argv
    assert argv[argv.index("-s") + 1] == "read-only"
    workdir = Path(argv[argv.index("-C") + 1])
    assert workdir.name == "empty" and not workdir.exists()  # temp folder cleaned up
    # The rubric and the pair go in on stdin, never on the command line.
    assert judge.system("rewrite") in kwargs["input"]
    assert kwargs["input"].endswith("<A>x</A><B>y</B>")
    assert not any("<A>" in part for part in argv)


def test_a_fenced_reply_still_parses():
    reply = '```json\n{"winner": "tie", "reason": "Same."}\n```'
    assert judge_codex.parse(reply).winner == "tie"


@pytest.mark.parametrize("runner, message", [
    (_Runner(None, returncode=2), "exited 2"),
    (_Runner(None), "no final message"),
    (_Runner("I cannot decide."), "no JSON verdict"),
])
def test_a_failed_session_raises_for_the_batch_to_record(runner, message):
    ask = judge_codex.codex_asker("gpt-6.1-sol", runner=runner)
    with pytest.raises(RuntimeError, match=message):
        ask("<A>x</A><B>y</B>", "rewrite")
