"""SQLite restart/concurrency contract, synthetic identities only."""

import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest


def store(path):
    assert importlib.util.find_spec("homebox_companion.research_jobs") is not None
    from homebox_companion.research_jobs import JobStore

    return JobStore(path)


def test_enqueue_idempotency_is_atomic_and_payload_bound(tmp_path):
    path = tmp_path / "research.sqlite3"
    db = store(path)

    def enqueue(_):
        return store(path).enqueue("scope", "item", "key", {"identity": "AB-123"})["id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(enqueue, range(16)))
    assert len(set(ids)) == 1
    with pytest.raises(ValueError, match="Idempotency"):
        db.enqueue("scope", "item", "key", {"identity": "OTHER"})
    assert db.get(ids[0], "foreign") is None
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: store(path).claim(ids[0], "scope"), range(8)))
    assert sum(claimed) == 1


def test_actual_process_restart_never_redispatches_unknown_post(tmp_path):
    path = tmp_path / "research.sqlite3"
    db = store(path)
    pending = db.enqueue("scope", "item1", "k1", {"identity": "AB-123"})
    sent = db.enqueue("scope", "item2", "k2", {"identity": "AB-124"})
    assert db.claim(sent["id"], "scope")
    assert db.dispatch(sent["id"])
    code = (
        "from homebox_companion.research_jobs import JobStore; import sys,json; "
        's=JobStore(sys.argv[1]);s.recover();print(json.dumps(s.list("scope")))'
    )
    result = subprocess.run([sys.executable, "-c", code, str(path)], check=True, capture_output=True, text=True)
    rows = {r["id"]: r for r in json.loads(result.stdout)}
    assert rows[pending["id"]]["state"] == "needs_auth"
    assert rows[sent["id"]]["state"] == "unknown_outcome"
    assert not db.claim(sent["id"], "scope")
    assert "token" not in path.read_bytes().decode("latin1")


def test_singleflight_alias_keeps_idempotency_after_completion(tmp_path):
    db = store(tmp_path / "research.sqlite3")
    first = db.enqueue("scope", "item", "key1", {})
    alias = db.enqueue("scope", "item", "key2", {})
    assert first["id"] == alias["id"]
    assert db.claim(first["id"], "scope")
    assert db.dispatch(first["id"])
    db.finish(first["id"], "matched", {})
    assert db.enqueue("scope", "item", "key2", {})["id"] == first["id"]


def test_cancel_wins_over_result_and_queue_is_bounded(tmp_path):
    db = store(tmp_path / "research.sqlite3")
    row = db.enqueue("scope", "item", "key", {})
    assert db.claim(row["id"], "scope")
    assert db.dispatch(row["id"])
    db.cancel(row["id"], "scope")
    db.finish(row["id"], "matched", {"claims": ["must not escape cancel"]})
    assert db.get(row["id"], "scope")["state"] == "cancelled"
    assert db.get(row["id"], "scope")["result"] is None
    for i in range(10):
        db.enqueue("scope", str(i), str(i), {})
    with pytest.raises(ValueError, match="Queue"):
        db.enqueue("scope", "overflow", "overflow", {})


@pytest.mark.parametrize(
    "point,expected",
    [
        ("queued", "needs_auth"),
        ("running", "needs_auth"),
        ("dispatching", "unknown_outcome"),
        ("accepted", "unknown_outcome"),
        ("persisted", "matched"),
    ],
)
def test_crash_checkpoints_do_not_replay_paid_post(tmp_path, point, expected):
    path = tmp_path / "research.sqlite3"
    code = """
import sys,os
from pathlib import Path
from homebox_companion.research_jobs import JobStore
s=JobStore(Path(sys.argv[1])); point=sys.argv[2]
r=s.enqueue('scope','item','key',{})
if point != 'queued': s.claim(r['id'],'scope')
if point in {'dispatching','accepted','persisted'}: s.dispatch(r['id'])
if point in {'accepted','persisted'}: Path(sys.argv[1]+'.calls').write_text('1')
if point == 'persisted': s.finish(r['id'],'matched',{'claims':[]})
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", code, str(path), point], check=True)
    db = store(path)
    db.recover()
    row = db.list("scope")[0]
    assert row["state"] == expected
    assert not db.claim(row["id"], "scope")


def test_sqlite_backup_restore_and_expiry(tmp_path):
    import sqlite3
    import time

    db = store(tmp_path / "research.sqlite3")
    row = db.enqueue("scope", "item", "key", {})
    backup = tmp_path / "backup.sqlite3"
    with sqlite3.connect(db.path) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    restored = store(backup)
    assert restored.get(row["id"], "scope")["payload"] == {}
    with restored.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        conn.execute("UPDATE jobs SET expires=?", (time.time() - 1,))
    assert restored.get(row["id"], "scope") is None
    restored.enqueue("scope", "other", "other", {})
    with restored.connection() as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
