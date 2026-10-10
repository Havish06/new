"""Workspace awareness (doc §20-21, §31-32). Opt-in, local-first, high-level signals only.

The desktop agent sends: active application name, project name (e.g. from the VS Code window
title), idle seconds. Never keystrokes, screenshots, window contents or file contents.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from .user_settings import get_settings

ALLOWED_FIELDS = ("app", "project", "idle_seconds", "active_seconds")


def _emit(etype: str, payload: dict, dedupe: str) -> None:
    db.insert("events", {"id": db.new_id("ev"), "type": etype, "payload": payload, "dedupe_key": dedupe,
                         "processed": 0, "created_at": db.now_iso()}, or_ignore=True)


def ingest(payload: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    ws = s.get("workspace") or {}
    if not ws.get("enabled"):
        return {"accepted": False, "reason": "Workspace awareness is disabled"}
    if ws.get("paused"):
        return {"accepted": False, "reason": "Monitoring paused"}
    data = {k: payload.get(k) for k in ALLOWED_FIELDS}          # whitelist: drop anything else
    idle = int(data.get("idle_seconds") or 0)
    prev = db.fetch_one("SELECT * FROM activity_events ORDER BY ts DESC LIMIT 1")
    row = {"id": db.new_id("act"), "ts": db.now_iso(), "app": (data.get("app") or "")[:80] or None,
           "project": (data.get("project") or "")[:80] or None, "idle_seconds": idle,
           "active_seconds": int(data.get("active_seconds") or 0)}
    db.insert("activity_events", row)
    if row["project"] and idle < 120:
        path = payload.get("project_path") if isinstance(payload.get("project_path"), str) else None
        existing = db.fetch_one("SELECT * FROM projects WHERE name=?", (row["project"],))
        if existing:
            db.update("projects", existing["id"], {"last_active_at": row["ts"], **({"path": path} if path else {})})
        else:
            db.insert("projects", {"id": db.new_id("prj"), "name": row["project"], "path": path,
                                   "last_active_at": row["ts"]})
    threshold = int(ws.get("idle_threshold_min") or 15) * 60
    prev_idle = int(prev["idle_seconds"] or 0) if prev else 0
    if idle >= threshold and prev_idle < threshold:
        idle_start = datetime.now(timezone.utc) - timedelta(seconds=idle)
        last_active = db.fetch_one("SELECT app, project FROM activity_events WHERE idle_seconds<120 "
                                   "ORDER BY ts DESC LIMIT 1") or {}
        _emit("USER_IDLE", {"idle_min": idle // 60, "last_app": last_active.get("app"),
                            "last_project": last_active.get("project")},
              f"idle:{idle_start:%Y%m%d%H%M}")
    elif prev_idle >= threshold and idle < 60:
        _emit("USER_RETURNED", {"was_idle_min": prev_idle // 60}, f"returned:{row['ts'][:16]}")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    db.execute("DELETE FROM activity_events WHERE ts<?", (cutoff,))
    return {"accepted": True}


def active_streak_minutes() -> tuple[float, str | None]:
    """Minutes of continuous activity (gaps of idle >= 5 min break the streak)."""
    rows = db.fetch_all("SELECT ts, idle_seconds FROM activity_events ORDER BY ts DESC LIMIT 400")
    if not rows or (rows[0]["idle_seconds"] or 0) >= 300:
        return 0.0, None
    start = rows[0]["ts"]
    for r in rows:
        if (r["idle_seconds"] or 0) >= 300:
            break
        start = r["ts"]
    mins = (datetime.fromisoformat(rows[0]["ts"]) - datetime.fromisoformat(start)).total_seconds() / 60
    if (datetime.now(timezone.utc) - datetime.fromisoformat(rows[0]["ts"])) > timedelta(minutes=5):
        return 0.0, None            # agent stopped reporting
    return mins, start


def status() -> dict[str, Any]:
    s = get_settings()
    last = db.fetch_one("SELECT * FROM activity_events ORDER BY ts DESC LIMIT 1")
    streak, _ = active_streak_minutes()
    online = bool(last) and (datetime.now(timezone.utc) - datetime.fromisoformat(last["ts"])) < timedelta(minutes=3)
    return {"enabled": (s.get("workspace") or {}).get("enabled", False),
            "paused": (s.get("workspace") or {}).get("paused", False),
            "agent_online": online, "app": last["app"] if last else None,
            "project": last["project"] if last else None,
            "idle_min": round((last["idle_seconds"] or 0) / 60, 1) if last else None,
            "active_streak_min": round(streak), "last_seen": last["ts"] if last else None,
            "projects": db.fetch_all("SELECT * FROM projects ORDER BY last_active_at DESC LIMIT 10")}


def clear_activity() -> None:
    db.execute("DELETE FROM activity_events")
