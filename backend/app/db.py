"""SQLite persistence layer (stdlib only).

SQLite keeps DecisionOS runnable on a single laptop with zero setup. The schema mirrors the
entities in the design doc, so moving to PostgreSQL later is a mechanical change.
JSON-shaped fields are stored as TEXT and decoded by the helpers below.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import settings

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,              -- preference | decision | task | project | habit | interest | fact
    content TEXT NOT NULL,
    source TEXT NOT NULL,            -- explicit | inferred | system
    status TEXT NOT NULL,            -- active | proposed | rejected
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    signal TEXT NOT NULL,
    decision_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    path TEXT,
    last_active_at TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    decision_type TEXT,
    status TEXT NOT NULL,            -- researching | ready | accepted | planned | failed
    spec TEXT DEFAULT '{}',
    result TEXT DEFAULT '{}',
    candidates TEXT DEFAULT '[]',
    research TEXT DEFAULT '[]',
    plan TEXT DEFAULT 'null',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL,            -- pending | in_progress | done | cancelled
    priority TEXT NOT NULL,          -- low | medium | high | critical
    deadline TEXT,
    scheduled_start TEXT,
    duration_min INTEGER,
    source_decision TEXT,
    project TEXT,
    reminder_at TEXT,
    calendar_event_id TEXT,
    meta TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    remind_at TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL,            -- pending | fired | acted | dismissed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    location TEXT,
    description TEXT,
    source_decision TEXT,
    task_id TEXT,
    provider TEXT NOT NULL,          -- local | google
    external_id TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    app TEXT,
    project TEXT,
    idle_seconds INTEGER,
    active_seconds INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    dedupe_key TEXT UNIQUE,
    processed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interventions (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    score REAL,
    components TEXT DEFAULT '{}',
    status TEXT NOT NULL,            -- delivered | suppressed
    reason TEXT,
    actions TEXT DEFAULT '[]',
    seen INTEGER DEFAULT 0,
    response TEXT,                   -- acted | dismissed | snoozed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY,
    engine TEXT,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_events(ts);
CREATE INDEX IF NOT EXISTS idx_interventions_created ON interventions(created_at);
"""

JSON_FIELDS = {"value", "meta", "spec", "result", "candidates", "research", "plan",
               "payload", "components", "actions", "response_json", "data"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for k in row.keys():
        v = row[k]
        if k in JSON_FIELDS and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        out[k] = v
    return out


def _encode(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v, default=str) if k in JSON_FIELDS and not isinstance(v, str) else v)
            for k, v in values.items()}


def fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with db() as conn:
        return _decode(conn.execute(sql, params).fetchone())


def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with db() as conn:
        return [_decode(r) for r in conn.execute(sql, params).fetchall()]  # type: ignore[misc]


def insert(table: str, values: dict[str, Any], or_ignore: bool = False) -> dict[str, Any]:
    enc = _encode(values)
    cols = ", ".join(enc.keys())
    marks = ", ".join("?" for _ in enc)
    verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
    with db() as conn:
        conn.execute(f"{verb} INTO {table} ({cols}) VALUES ({marks})", tuple(enc.values()))
    return values


def upsert(table: str, values: dict[str, Any], key: str) -> None:
    enc = _encode(values)
    cols = ", ".join(enc.keys())
    marks = ", ".join("?" for _ in enc)
    updates = ", ".join(f"{c}=excluded.{c}" for c in enc if c != key)
    with db() as conn:
        conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT({key}) DO UPDATE SET {updates}",
            tuple(enc.values()),
        )


def update(table: str, row_id: str, values: dict[str, Any], key: str = "id") -> None:
    if not values:
        return
    enc = _encode(values)
    sets = ", ".join(f"{c}=?" for c in enc)
    with db() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE {key}=?", (*enc.values(), row_id))


def delete(table: str, row_id: str, key: str = "id") -> None:
    with db() as conn:
        conn.execute(f"DELETE FROM {table} WHERE {key}=?", (row_id,))


def execute(sql: str, params: tuple = ()) -> int:
    with db() as conn:
        return conn.execute(sql, params).rowcount
