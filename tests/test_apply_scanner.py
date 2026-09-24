"""Frame identity and read-only snapshot behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from resume_tailor.apply import scanner


class _Locator:
    async def count(self):
        return 1


class _Frame:
    def __init__(self, value: str):
        self.value = value
        self.calls = []
        self.detached = False

    async def evaluate(self, script):
        self.calls.append(script)
        return {
            "document_generation": "123", "fields": [{
                "selector": "#school", "label": "School", "control_kind": "text",
                "current_value": self.value, "options": [],
            }],
        }

    def is_detached(self):
        return self.detached

    def locator(self, selector):
        assert selector == "#school"
        return _Locator()


def test_scanner_keeps_same_selector_in_separate_frames_distinct():
    frames = [_Frame("UC Irvine"), _Frame("Other")]
    snapshot = asyncio.run(scanner.scan(SimpleNamespace(frames=frames)))
    assert len(snapshot.fields) == 2
    assert snapshot.fields[0].field_id != snapshot.fields[1].field_id
    assert snapshot.fields[0].frame_id != snapshot.fields[1].frame_id
    assert all(".click(" not in frame.calls[0] and ".fill(" not in frame.calls[0] for frame in frames)


def test_scanner_rejects_replaced_frame():
    frame = _Frame("")
    snapshot = asyncio.run(scanner.scan(SimpleNamespace(frames=[frame])))
    frame.detached = True
    with pytest.raises(ValueError, match="frame_replaced"):
        asyncio.run(snapshot.locator(snapshot.fields[0]))
