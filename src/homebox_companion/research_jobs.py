"""Small durable research queue. Contains no credentials or inventory copies."""

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Unsupported research database version")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, item TEXT NOT NULL,
                key TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                expires REAL NOT NULL, UNIQUE(scope,key))""")
            db.execute("""CREATE TABLE IF NOT EXISTS aliases (
                scope TEXT NOT NULL, key TEXT NOT NULL, job TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                PRIMARY KEY(scope,key))""")
            db.execute("INSERT OR IGNORE INTO aliases SELECT scope,key,id FROM jobs")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def row(row):
        if row is None:
            return None
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        out["result"] = json.loads(out["result"]) if out["result"] else None
        return out

    def enqueue(self, scope: str, item: str, key: str, payload: dict):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(encoded) > 16000 or len(key) > 100:
            raise ValueError("Payload too large")
        digest = hashlib.sha256((item + "\n" + encoded).encode()).hexdigest()
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM jobs WHERE expires < ? AND state NOT IN ('running','dispatching')", (now,))
            existing = db.execute(
                "SELECT jobs.* FROM jobs JOIN aliases ON jobs.id=aliases.job WHERE aliases.scope=? AND aliases.key=?",
                (scope, key),
            ).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise ValueError("Idempotency key payload conflict")
                return self.row(existing)
            active = db.execute(
                "SELECT * FROM jobs WHERE scope=? AND digest=? "
                "AND state IN ('queued','running','dispatching','needs_auth')",
                (scope, digest),
            ).fetchone()
            if active:
                if db.execute("SELECT count(*) FROM aliases WHERE job=?", (active["id"],)).fetchone()[0] >= 10:
                    raise ValueError("Queue idempotency alias limit reached")
                db.execute("INSERT INTO aliases VALUES (?,?,?)", (scope, key, active["id"]))
                return self.row(active)
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE scope=? AND state IN ('queued','running','dispatching','needs_auth')",
                (scope,),
            ).fetchone()[0]
            total = db.execute("SELECT count(*) FROM jobs").fetchone()[0]
            if count >= 10 or total >= 100:
                raise ValueError("Queue capacity reached")
            id_ = str(uuid4())
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,'queued',NULL,?,?,?)",
                (id_, scope, item, key, digest, encoded, now, now, now + 7 * 86400),
            )
            db.execute("INSERT INTO aliases VALUES (?,?,?)", (scope, key, id_))
            return self.row(db.execute("SELECT * FROM jobs WHERE id=?", (id_,)).fetchone())

    def get(self, id_: str, scope: str):
        with self.connection() as db:
            return self.row(
                db.execute(
                    "SELECT * FROM jobs WHERE id=? AND scope=? AND expires>?", (id_, scope, time.time())
                ).fetchone()
            )

    def list(self, scope: str):
        with self.connection() as db:
            return [
                self.row(row)
                for row in db.execute(
                    "SELECT * FROM jobs WHERE scope=? AND expires>? ORDER BY created DESC", (scope, time.time())
                )
            ]

    def claim(self, id_: str, scope: str) -> bool:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT count(*) FROM jobs WHERE state IN ('running','dispatching')").fetchone()[0] >= 2:
                return False
            if db.execute(
                "SELECT count(*) FROM jobs WHERE scope=? AND state IN ('running','dispatching')", (scope,)
            ).fetchone()[0]:
                return False
            return (
                db.execute(
                    "UPDATE jobs SET state='running',updated=? WHERE id=? AND scope=? AND state='queued' AND expires>?",
                    (time.time(), id_, scope, time.time()),
                ).rowcount
                == 1
            )

    def dispatch(self, id_: str) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE jobs SET state='dispatching',updated=? WHERE id=? AND state='running'", (time.time(), id_)
                ).rowcount
                == 1
            )

    def finish(self, id_: str, state: str, result: dict | None = None):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state=?,result=?,updated=? WHERE id=? "
                "AND state IN ('running','dispatching','applying')",
                (state, json.dumps(result) if result is not None else None, time.time(), id_),
            )

    def cancel(self, id_: str, scope: str):
        with self.connection() as db:
            db.execute(
                "UPDATE jobs SET state='cancelled',result=NULL,updated=? WHERE id=? AND scope=?",
                (time.time(), id_, scope),
            )

    def claim_apply(self, id_: str, scope: str) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE jobs SET state='applying',updated=? WHERE id=? AND scope=? AND state='matched'",
                    (time.time(), id_, scope),
                ).rowcount
                == 1
            )

    def recover(self):
        """Only at exclusive application startup, never from another worker process."""
        with self.connection() as db:
            db.execute("UPDATE jobs SET state='unknown_outcome' WHERE state='dispatching'")
            db.execute("UPDATE jobs SET state='apply_unknown' WHERE state='applying'")
            db.execute("UPDATE jobs SET state='needs_auth' WHERE state IN ('queued','running')")

    def resume(self, id_: str, scope: str) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE jobs SET state='queued',updated=? WHERE id=? AND scope=? AND state='needs_auth'",
                    (time.time(), id_, scope),
                ).rowcount
                == 1
            )
