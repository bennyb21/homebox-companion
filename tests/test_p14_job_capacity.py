"""Cancellation must not release capacity while provider execution is active."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from test_research_api import BODY, TYPE
from test_research_api import harness as harness


@pytest.mark.asyncio
async def test_cancelled_dispatch_holds_capacity_until_provider_finishes(harness, tmp_path):
    app, gateway = harness
    app.state.research_db_path = tmp_path / "jobs.sqlite3"
    current = {
        "id": "item1",
        "name": "Synthetic",
        "entityType": {"id": TYPE},
        "fields": [{"id": "f1", "name": "Specifications", "type": "text", "textValue": ""}],
        "tags": [],
    }
    gateway.get_current_user = AsyncMock(return_value={"id": "user1"})
    gateway.get_item = AsyncMock(side_effect=lambda _: deepcopy(current))
    gate = asyncio.Event()
    started = asyncio.Event()
    result = app.state.research_provider.research.return_value

    async def blocked(identity):
        started.set()
        await gate.wait()
        return result

    app.state.research_provider.research.side_effect = blocked
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:

            async def enqueue(key):
                response = await client.post(
                    "/api/research/jobs",
                    json={"item_id": "item1", "identity": BODY["identity"], "idempotency_key": key},
                )
                assert response.status_code == 202
                return response.json()["id"]

            first = await enqueue("first")
            await asyncio.wait_for(started.wait(), 3)
            assert (await client.post(f"/api/research/jobs/{first}/cancel")).status_code == 200
            await enqueue("second")
            await asyncio.sleep(0.2)  # allow multiple scheduler ticks with provider held
            assert app.state.research_provider.research.await_count == 1
            gate.set()
            async with asyncio.timeout(3):
                while app.state.research_provider.research.await_count < 2:
                    await asyncio.sleep(0.01)
            assert (await client.get(f"/api/research/jobs/{first}")).json()["state"] == "cancelled"
    finally:
        gate.set()
        await app.state.research_jobs.close()


@pytest.mark.asyncio
async def test_cancelled_tasks_retain_global_capacity_across_scopes(tmp_path):
    from server.services.research_jobs import ResearchJobs

    runner = ResearchJobs(tmp_path / "global.sqlite3")
    gate = asyncio.Event()
    started = []

    async def execute(row, gateway, provider):
        assert runner.db.dispatch(row["id"])
        started.append(row["scope"])
        await gate.wait()
        runner.db.finish(row["id"], "matched", {})

    runner.execute = execute
    try:
        for owner in ("a", "b"):
            row = runner.db.enqueue(owner, "item", "first", {})
            runner.bind(row, None, None)
            async with asyncio.timeout(3):
                while owner not in started:
                    await asyncio.sleep(0.01)
            runner.db.cancel(row["id"], owner)
        row = runner.db.enqueue("c", "item", "third", {})
        runner.bind(row, None, None)
        await asyncio.sleep(0.2)
        assert started == ["a", "b"]
        gate.set()
        async with asyncio.timeout(3):
            while "c" not in started:
                await asyncio.sleep(0.01)
    finally:
        gate.set()
        await runner.close()
