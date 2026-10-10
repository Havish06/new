"""Calendar abstraction (doc §17).

Events always live in DecisionOS's own store (so the dashboard and the .ics feed work with no
account). If the user explicitly connects Google Calendar, events are also pushed there via a
provider implementing the same interface. New providers (Yahoo/CalDAV, Outlook) plug in here.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from ..config import settings

log = logging.getLogger("decisionos.calendar")


class CalendarProvider(ABC):
    name: str

    @abstractmethod
    def create_event(self, event: dict) -> str | None: ...

    @abstractmethod
    def update_event(self, external_id: str, event: dict) -> None: ...

    @abstractmethod
    def delete_event(self, external_id: str) -> None: ...


class LocalProvider(CalendarProvider):
    """No external sync — events are served via the DecisionOS .ics feed."""
    name = "local"

    def create_event(self, event: dict) -> str | None:
        return None

    def update_event(self, external_id: str, event: dict) -> None:
        return None

    def delete_event(self, external_id: str) -> None:
        return None


# ------------------------------------------------------------------ Google Calendar (OAuth, REST, stdlib only)
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def google_redirect_uri() -> str:
    return f"{settings.public_backend_url}/api/calendar/google/callback"


def google_auth_url(state: str) -> str:
    q = {"client_id": settings.google_client_id, "redirect_uri": google_redirect_uri(), "response_type": "code",
         "scope": GOOGLE_SCOPE, "access_type": "offline", "prompt": "consent", "state": state}
    return f"{GOOGLE_AUTH}?{urllib.parse.urlencode(q)}"


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def google_exchange_code(code: str) -> None:
    tok = _post_form(GOOGLE_TOKEN, {"code": code, "client_id": settings.google_client_id,
                                    "client_secret": settings.google_client_secret,
                                    "redirect_uri": google_redirect_uri(), "grant_type": "authorization_code"})
    tok["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)) - 60)).isoformat()
    db.upsert("oauth_tokens", {"provider": "google", "data": tok}, key="provider")


def google_disconnect() -> None:
    db.delete("oauth_tokens", "google", key="provider")


class GoogleProvider(CalendarProvider):
    name = "google"

    def _token(self) -> str:
        row = db.fetch_one("SELECT data FROM oauth_tokens WHERE provider='google'")
        if not row:
            raise RuntimeError("Google Calendar not connected")
        tok = row["data"]
        if datetime.fromisoformat(tok["expires_at"]) <= datetime.now(timezone.utc):
            new = _post_form(GOOGLE_TOKEN, {"client_id": settings.google_client_id,
                                            "client_secret": settings.google_client_secret,
                                            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
            tok.update(new)
            tok["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(new.get("expires_in", 3600)) - 60)).isoformat()
            db.upsert("oauth_tokens", {"provider": "google", "data": tok}, key="provider")
        return tok["access_token"]

    def _req(self, method: str, url: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}

    @staticmethod
    def _body(e: dict) -> dict:
        return {"summary": e["title"], "location": e.get("location") or "", "description": e.get("description") or "",
                "start": {"dateTime": e["start"]}, "end": {"dateTime": e["end"]},
                "reminders": {"useDefault": True}}

    def create_event(self, event: dict) -> str | None:
        return self._req("POST", GOOGLE_EVENTS, self._body(event)).get("id")

    def update_event(self, external_id: str, event: dict) -> None:
        self._req("PATCH", f"{GOOGLE_EVENTS}/{external_id}", self._body(event))

    def delete_event(self, external_id: str) -> None:
        self._req("DELETE", f"{GOOGLE_EVENTS}/{external_id}")


def google_connected() -> bool:
    return db.fetch_one("SELECT provider FROM oauth_tokens WHERE provider='google'") is not None


def active_provider() -> CalendarProvider:
    return GoogleProvider() if google_connected() else LocalProvider()


# ------------------------------------------------------------------ service
def create_event(title: str, start: str, end: str, location: str | None = None, description: str | None = None,
                 source_decision: str | None = None, task_id: str | None = None) -> dict:
    row = {"id": db.new_id("evt"), "title": title, "start": start, "end": end, "location": location,
           "description": description, "source_decision": source_decision, "task_id": task_id,
           "provider": "local", "external_id": None, "created_at": db.now_iso()}
    provider = active_provider()
    if provider.name != "local":
        try:
            row["external_id"] = provider.create_event(row)
            row["provider"] = provider.name
        except Exception as exc:
            log.warning("calendar sync failed: %s", exc)
            row["description"] = (description or "") + "\n[sync to external calendar failed]"
    db.insert("calendar_events", row)
    return row


def update_event(event_id: str, patch: dict) -> dict | None:
    allowed = {k: v for k, v in patch.items() if k in ("title", "start", "end", "location", "description")}
    db.update("calendar_events", event_id, allowed)
    row = db.fetch_one("SELECT * FROM calendar_events WHERE id=?", (event_id,))
    if row and row["external_id"] and row["provider"] == "google":
        try:
            GoogleProvider().update_event(row["external_id"], row)
        except Exception as exc:
            log.warning("calendar update sync failed: %s", exc)
    return row


def delete_event(event_id: str) -> None:
    row = db.fetch_one("SELECT * FROM calendar_events WHERE id=?", (event_id,))
    if row and row["external_id"] and row["provider"] == "google":
        try:
            GoogleProvider().delete_event(row["external_id"])
        except Exception as exc:
            log.warning("calendar delete sync failed: %s", exc)
    db.delete("calendar_events", event_id)


def list_events(start: str | None = None, end: str | None = None) -> list[dict]:
    rows = db.fetch_all("SELECT * FROM calendar_events ORDER BY start")
    def inside(r: dict) -> bool:
        s = datetime.fromisoformat(r["start"])
        return (not start or s >= datetime.fromisoformat(start)) and (not end or s <= datetime.fromisoformat(end))
    return [r for r in rows if inside(r)]


def _ics_dt(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ics_escape(s: str | None) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_feed(events: list[dict] | None = None) -> str:
    events = events if events is not None else list_events()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DecisionOS//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:DecisionOS"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:{e['id']}@decisionos", f"DTSTAMP:{stamp}",
                  f"DTSTART:{_ics_dt(e['start'])}", f"DTEND:{_ics_dt(e['end'])}",
                  f"SUMMARY:{_ics_escape(e['title'])}"]
        if e.get("location"):
            lines.append(f"LOCATION:{_ics_escape(e['location'])}")
        if e.get("description"):
            lines.append(f"DESCRIPTION:{_ics_escape(e['description'])}")
        lines += ["BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(e['title'])}",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
