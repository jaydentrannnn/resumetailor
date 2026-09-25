"""Hermetic protocol checks for the selected-tab CDP relay."""

import pytest

from resume_tailor.apply.cdp_relay import Relay


@pytest.mark.asyncio
async def test_relay_emulates_browser_and_independent_page_sessions():
    relay = Relay()
    relay.target = {
        "targetId": "chosen-tab",
        "type": "page",
        "url": "http://127.0.0.1/job",
        "title": "Synthetic job",
        "attached": True,
    }

    assert (await relay.command("Browser.getVersion", {}, None))["protocolVersion"] == "1.3"
    assert (await relay.command("Target.getTargets", {}, None))["targetInfos"] == [relay.target]
    browser_session = (await relay.command("Target.attachToBrowserTarget", {}, None))["sessionId"]
    first = (await relay.command("Target.attachToTarget", {}, browser_session))["sessionId"]
    second = (await relay.command("Target.attachToTarget", {}, browser_session))["sessionId"]
    assert first != second
    assert {first, second} <= relay.page_sessions
    assert (await relay.command("Target.createTarget", {"url": "about:blank"}, None)) == {
        "targetId": "chosen-tab"
    }
    assert (await relay.command("Target.getTargetInfo", {}, first))["targetInfo"] == relay.target
    await relay.command("Target.detachFromTarget", {"sessionId": first}, browser_session)
    assert first not in relay.page_sessions
    assert second in relay.page_sessions
