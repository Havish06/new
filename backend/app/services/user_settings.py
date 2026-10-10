"""User-level preferences: name, home location, mode, quiet hours, workspace awareness."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .. import db
from ..config import settings as cfg

DEFAULTS: dict[str, Any] = {
    "name": "",
    "timezone": cfg.timezone,
    "currency": cfg.currency,
    "country": cfg.country,
    # Home/base location used for local searches and errand routing.
    "home": {"label": "", "lat": None, "lng": None},
    "mode": "normal",                     # focus | normal | assistant | quiet | sleep
    "quiet_hours": {"enabled": True, "start": "23:00", "end": "07:00", "allow_critical": True},
    "workspace": {
        "enabled": False,                 # opt-in, per the privacy architecture
        "paused": False,
        "idle_threshold_min": 15,
        "suggest_interests": False,       # "something you enjoy" suggestions need explicit opt-in
        "break_after_min": 120,
    },
    "notifications": {"browser": True, "desktop": True, "email": False, "telegram": False},
    "places": {},                         # saved places: {"college": {label, lat, lng}}
    "reminder_lead_min": 60,
    "transport": {"walk_max_km": 1.5, "walk_kmh": 4.5, "ride_kmh": 18, "ride_cost_per_km": 15},
}


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_settings() -> dict[str, Any]:
    row = db.fetch_one("SELECT value FROM settings WHERE key='user'")
    return _merge(DEFAULTS, row["value"] if row else {})


def update_settings(patch: dict[str, Any]) -> dict[str, Any]:
    merged = _merge(get_settings(), patch)
    db.upsert("settings", {"key": "user", "value": merged}, key="key")
    return merged


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().get("timezone") or cfg.timezone)
    except Exception:
        return ZoneInfo("UTC")


def local_now() -> datetime:
    return datetime.now(tz())


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_quiet_hours(at: datetime | None = None, s: dict | None = None) -> bool:
    s = s or get_settings()
    q = s.get("quiet_hours", {})
    if not q.get("enabled"):
        return False
    at = (at or local_now()).astimezone(tz())
    start, end, t = _parse_hhmm(q["start"]), _parse_hhmm(q["end"]), at.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end   # window wraps midnight
