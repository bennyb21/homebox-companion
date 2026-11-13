"""Adverse/race tests using real scoped ASGI and SQLite, synthetic boundaries."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from test_research_api import BODY, TYPE, harness  # noqa: F401


@pytest_asyncio.fixture
async def jobs(request, tmp_path):
    app, gateway = request.getfixturevalue("harness")
    app.state.research_db_path = tmp_path / "research.sqlite3"
    current = {
        "id": "item1",
        "name": "Synthetic",
        "entityType": {"id": TYPE},
        "fields": [{"id": "f1", "name": "Specifications", "type": "text", "textValue": "manual"}],
        "tags": [],
    }
    gateway.get_current_user = AsyncMock(return_value={"id": "user1"})
    gateway.get_item = AsyncMock(side_effect=lambda _: deepcopy(current))

    async def update(_, payload):
        current.update(payload)
        return deepcopy(current)

    gateway.update_item = AsyncMock(side_effect=update)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        try:
            yield app, gateway, current, client
        finally:
            if hasattr(app.state, "research_jobs"):
                await app.state.research_jobs.close()


async def enqueue(client, key="key"):
    response = await client.post(
        "/api/research/jobs", json={"item_id": "item1", "identity": BODY["identity"], "idempotency_key": key}
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def settled(client, id_):
    for _ in range(200):
        response = await client.get(f"/api/research/jobs/{id_}")
        assert response.status_code == 200, response.text
        if response.json()["state"] not in {"queued", "running", "dispatching"}:
            return response.json()
        await asyncio.sleep(0.01)
    raise AssertionError("Job did not settle")


@pytest.mark.asyncio
async def test_concurrent_enqueue_and_apply_single_dispatch_write(jobs):
    app, gateway, current, client = jobs
    ids = await asyncio.gather(*(enqueue(client) for _ in range(8)))
    assert len(set(ids)) == 1
    assert (await settled(client, ids[0]))["state"] == "matched"
    responses = await asyncio.gather(
        *(client.post(f"/api/research/jobs/{ids[0]}/apply", json={"selected": [0]}) for _ in range(4))
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    app.state.research_provider.research.assert_awaited_once()
    gateway.update_item.assert_awaited_once()
    cancel = await client.post(f"/api/research/jobs/{ids[0]}/cancel")
    assert cancel.status_code == 409
    assert (await settled(client, ids[0]))["state"] == "applied"


@pytest.mark.asyncio
async def test_cancel_inflight_discards_result_without_write(jobs):
    app, gateway, current, client = jobs
    gate = asyncio.Event()
    started = asyncio.Event()
    result = app.state.research_provider.research.return_value

    async def delayed(identity):
        started.set()
        await gate.wait()
        return result

    app.state.research_provider.research.side_effect = delayed
    id_ = await enqueue(client)
    await asyncio.wait_for(started.wait(), 2)
    assert (await client.post(f"/api/research/jobs/{id_}/cancel")).status_code == 200
    gate.set()
    await asyncio.sleep(0.1)
    row = await settled(client, id_)
    assert row["state"] == "cancelled" and row["result"] is None
    gateway.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_current_identity_revalidated_before_dispatch(jobs):
    app, gateway, current, client = jobs
    gateway.get_current_user.return_value = {"id": "another-user"}
    id_ = await enqueue(client)
    assert (await settled(client, id_))["state"] == "needs_auth"
    app.state.research_provider.research.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_item_and_foreign_scope_cannot_apply(jobs):
    app, gateway, current, client = jobs
    id_ = await enqueue(client)
    await settled(client, id_)
    current["fields"][0]["textValue"] = ""
    assert (await client.post(f"/api/research/jobs/{id_}/apply", json={"selected": [0]})).status_code == 409
    gateway.access.identity_scope = "user2"
    assert (await client.get(f"/api/research/jobs/{id_}")).status_code == 404
    gateway.update_item.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_outcome_never_retries_or_resumes(jobs):
    app, gateway, current, client = jobs
    app.state.research_provider.research.side_effect = TimeoutError("private provider error")
    id_ = await enqueue(client)
    row = await settled(client, id_)
    assert row["state"] == "unknown_outcome"
    assert "private" not in str(row)
    assert (await client.post(f"/api/research/jobs/{id_}/resume")).status_code == 409
    await enqueue(client)
    await asyncio.sleep(0.1)
    app.state.research_provider.research.assert_awaited_once()


@pytest.mark.asyncio
async def test_changed_model_requires_new_cost_decision(jobs):
    from types import SimpleNamespace

    app, gateway, current, client = jobs
    app.state.research_provider.profile = SimpleNamespace(name="research", model="cheap", api_base=None)
    id_ = await enqueue(client)
    app.state.research_provider.profile.model = "other-model"
    assert (await settled(client, id_))["state"] == "stale"
    app.state.research_provider.research.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabling_policy_while_queued_prevents_dispatch(jobs):
    app, gateway, current, client = jobs
    id_ = await enqueue(client)
    app.state.research_provider = type("Disabled", (), {"configured": False})()
    assert (await settled(client, id_))["state"] == "disabled"
