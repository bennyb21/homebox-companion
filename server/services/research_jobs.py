"""Durable queue runner. Bearer gateways live only in memory, never in SQLite."""

import asyncio
import fcntl
from contextlib import suppress

from homebox_companion.research import ProductIdentity
from homebox_companion.research_jobs import JobStore


class ResearchJobs:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = path.with_suffix(".lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise RuntimeError("Research jobs require one application worker") from None
        self.db = JobStore(path)
        self.db.recover()
        self.credentials = {}
        self.tasks = {}
        self.apply_lock = asyncio.Lock()
        self.loop = asyncio.create_task(self.run())

    def bind(self, row, gateway, provider):
        if row["state"] == "queued":
            self.credentials[row["id"]] = (gateway, provider, row["scope"])

    async def run(self):
        while True:
            for id_, (gateway, provider, owner) in list(self.credentials.items()):
                if id_ in self.tasks:
                    continue
                row = self.db.get(id_, owner)
                if row is None or row["state"] != "queued":
                    self.credentials.pop(id_, None)
                elif self.db.claim(id_, row["scope"]):
                    task = asyncio.create_task(self.execute(row, gateway, provider))
                    self.tasks[id_] = task
            for id_, task in list(self.tasks.items()):
                if task.done():
                    with suppress(asyncio.CancelledError, Exception):
                        task.result()
                    self.tasks.pop(id_, None)
                    self.credentials.pop(id_, None)
            await asyncio.sleep(0.05)

    async def execute(self, row, gateway, provider):
        from server.api.research import fingerprint, proposals, scope
        from server.api.research_jobs import item_profile, policy_hash, values

        try:
            user = await gateway.get_current_user()
            if user["id"] != gateway.access.identity_scope:
                self.db.finish(row["id"], "needs_auth")
                return
            await scope(gateway)
            item, profile = await item_profile(gateway, row["item"])
            payload = row["payload"]
            if fingerprint(item) != payload["item_hash"] or fingerprint(profile) != payload["profile_hash"]:
                self.db.finish(row["id"], "stale")
                return
            provider = provider()
            if not provider.configured:
                self.db.finish(row["id"], "disabled")
                return
            if payload.get("policy_hash") != policy_hash(provider):
                self.db.finish(row["id"], "stale")
                return
            if not self.db.dispatch(row["id"]):
                return
            result = await provider.research(ProductIdentity.model_validate(payload["identity"]))
            self.db.finish(
                row["id"],
                result.status,
                {"research": result.model_dump(), "proposals": proposals(result, profile, values(item))},
            )
        except asyncio.CancelledError:
            # A dispatched call may have been accepted; never silently requeue it.
            self.db.finish(row["id"], "unknown_outcome")
            raise
        except Exception:
            current = self.db.get(row["id"], row["scope"])
            self.db.finish(
                row["id"], "unknown_outcome" if current and current["state"] == "dispatching" else "needs_auth"
            )

    async def close(self):
        self.loop.cancel()
        with suppress(asyncio.CancelledError):
            await self.loop
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.credentials.clear()
        self.lock_file.close()
