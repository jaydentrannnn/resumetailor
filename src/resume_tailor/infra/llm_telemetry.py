"""Observe the existing messages.parse interface without changing provider responses."""

from __future__ import annotations

from typing import Any

from . import telemetry


class _Messages:
    def __init__(self, owner: Client):
        self.owner = owner

    def parse(self, **kwargs):
        owner = self.owner
        with telemetry.call(owner.purpose, kwargs.get("model", ""), owner.origin):
            return owner.raw.messages.parse(**kwargs)


class _AsyncMessages:
    def __init__(self, owner: Client):
        self.owner = owner

    async def parse(self, **kwargs):
        owner = self.owner
        with telemetry.call(owner.purpose, kwargs.get("model", ""), owner.origin):
            return await owner.raw.messages.parse(**kwargs)


class Client:
    def __init__(self, raw: Any, purpose: str, origin: str, *, asynchronous: bool = False):
        self.raw, self.purpose, self.origin = raw, purpose, origin
        self.messages = _AsyncMessages(self) if asynchronous else _Messages(self)

    def __getattr__(self, name: str):
        return getattr(self.raw, name)

    async def __aenter__(self):
        await self.raw.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.raw.__aexit__(*args)


def wrap(raw: Any, purpose: str, origin: str, *, asynchronous: bool = False):
    return (
        Client(raw, purpose, origin, asynchronous=asynchronous)
        if telemetry.current() is not None
        else raw
    )
