"""Barrier regressions for research admission before asynchronous preflight."""

import asyncio
import time

import httpx
import pytest
from test_research_api import BODY
from test_research_api import harness as harness


@pytest.mark.asyncio
@pytest.mark.parametrize("occupied,admitted", [(0, 10), (95, 5)])
async def test_lookup_reserves_capacity_before_profile_await(harness, occupied, admitted):
    app, gateway = harness
    app.state.research_reviews = {
        str(i): {"scope": ("other", str(i)), "expires": time.monotonic() + 900} for i in range(occupied)
    }
    gate = asyncio.Event()
    entered = 0
    profile = gateway.get_capture_profile.return_value

    async def blocked(*args):
        nonlocal entered
        entered += 1
        await gate.wait()
        return profile

    gateway.get_capture_profile.side_effect = blocked
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        tasks = [asyncio.create_task(client.post("/api/research/lookups", json=BODY)) for _ in range(12)]
        try:
            async with asyncio.timeout(3):
                while entered + sum(t.done() for t in tasks) < 12:
                    await asyncio.sleep(0)
            assert entered == admitted
        finally:
            gate.set()
            responses = await asyncio.gather(*tasks)
    assert sorted(r.status_code for r in responses) == [200] * admitted + [429] * (12 - admitted)
    assert app.state.research_provider.research.await_count == admitted


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_failed_preflight_releases_reservation(harness, failure):
    app, gateway = harness
    gateway.get_capture_profile.side_effect = failure("preflight interrupted")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        with pytest.raises(failure):
            await client.post("/api/research/lookups", json=BODY)
    assert app.state.research_reviews == {}
    app.state.research_provider.research.assert_not_awaited()
