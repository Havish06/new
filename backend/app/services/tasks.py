"""Task, reminder and plan-commit services (doc §13, §16, §37)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .. import db
from . import calendar, memory
from .user_settings import get_settings, local_now

PRIORITIES = ("low", "medium", "high", "critical")


def get_task(task_id: str) -> dict | None:
    return db.fetch_one("SELECT * FROM tasks WHERE id=?", (task_id,))


def list_tasks(status: str | None = None) -> list[dict]:
    if status == "open":
        return db.fetch_all("SELECT * FROM tasks WHERE status IN ('pending','in_progress') "
                            "ORDER BY COALESCE(scheduled_start, deadline, created_at)")
    if status:
        return db.fetch_all("SELECT * FROM tasks WHERE status=? ORDER BY COALESCE(scheduled_start, deadline, created_at)", (status,))
    return db.fetch_all("SELECT * FROM tasks ORDER BY status='done', COALESCE(scheduled_start, deadline, created_at)")


def create_task(title: str, deadline: str | None = None, priority: str = "medium", notes: str | None = None,
                source_decision: str | None = None, scheduled_start: str | None = None,
                duration_min: int | None = None, project: str | None = None, reminder_at: str | None = None,
                meta: dict | None = None) -> dict:
    row = {"id": db.new_id("task"), "title": title.strip(), "notes": notes, "status": "pending",
           "priority": priority if priority in PRIORITIES else "medium", "deadline": deadline,
           "scheduled_start": scheduled_start, "duration_min": duration_min, "source_decision": source_decision,
           "project": project, "reminder_at": reminder_at, "calendar_event_id": None, "meta": meta or {},
           "created_at": db.now_iso(), "updated_at": db.now_iso(), "completed_at": None}
    db.insert("tasks", row)
    if reminder_at:
        add_reminder(row["id"], reminder_at)
    return row


def add_reminder(task_id: str | None, remind_at: str, message: str | None = None) -> dict:
    row = {"id": db.new_id("rem"), "task_id": task_id, "remind_at": remind_at, "message": message,
           "status": "pending", "created_at": db.now_iso()}
    db.insert("reminders", row)
    return row


def update_task(task_id: str, patch: dict[str, Any]) -> dict | None:
    allowed = {k: v for k, v in patch.items()
               if k in ("title", "notes", "status", "priority", "deadline", "scheduled_start", "duration_min",
                        "project", "reminder_at")}
    if not allowed:
        return get_task(task_id)
    old = get_task(task_id)
    allowed["updated_at"] = db.now_iso()
    if allowed.get("status") == "done":
        allowed["completed_at"] = db.now_iso()
        db.execute("UPDATE reminders SET status='acted' WHERE task_id=? AND status IN ('pending','fired')", (task_id,))
    db.update("tasks", task_id, allowed)
    if old and "deadline" in allowed and allowed["deadline"] != old["deadline"]:
        db.insert("events", {"id": db.new_id("ev"), "type": "DEADLINE_CHANGED",
                             "payload": {"task_id": task_id, "old": old["deadline"], "new": allowed["deadline"]},
                             "dedupe_key": f"deadline:{task_id}:{allowed['deadline']}", "processed": 0,
                             "created_at": db.now_iso()}, or_ignore=True)
    if old and "reminder_at" in allowed and allowed["reminder_at"]:
        db.execute("DELETE FROM reminders WHERE task_id=? AND status='pending'", (task_id,))
        add_reminder(task_id, allowed["reminder_at"])
    return get_task(task_id)


def complete_task(task_id: str) -> dict | None:
    return update_task(task_id, {"status": "done"})


def delete_task(task_id: str) -> None:
    db.execute("DELETE FROM reminders WHERE task_id=?", (task_id,))
    db.delete("tasks", task_id)


def list_reminders(status: str | None = "pending") -> list[dict]:
    if status:
        return db.fetch_all("SELECT r.*, t.title AS task_title FROM reminders r LEFT JOIN tasks t ON t.id=r.task_id "
                            "WHERE r.status=? ORDER BY r.remind_at", (status,))
    return db.fetch_all("SELECT r.*, t.title AS task_title FROM reminders r LEFT JOIN tasks t ON t.id=r.task_id ORDER BY r.remind_at")


# ------------------------------------------------------------------ "Remind me to ..."
def reminder_from_chat(task: str, when_iso: str | None, now: datetime | None = None) -> dict:
    """'Remind me to submit this tomorrow at 6 PM' -> task due 6 PM + reminder (lead time before, if in future)."""
    now = now or local_now()
    lead = int(get_settings().get("reminder_lead_min") or 60)
    if not when_iso:
        due = None
        remind = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    else:
        due = datetime.fromisoformat(when_iso)
        remind = due - timedelta(minutes=lead)
        if remind <= now:
            remind = due
    title = task[:1].upper() + task[1:] if task else "Reminder"
    t = create_task(title, deadline=due.isoformat() if due else None, priority="high" if due else "medium",
                    reminder_at=remind.isoformat(), meta={"origin": "chat"})
    return {"task": t, "remind_at": remind.isoformat(), "due": due.isoformat() if due else None}


# ------------------------------------------------------------------ plan -> tasks / calendar / reminders
def commit_plan(decision: dict, step_indexes: list[int] | None, add_to_calendar: bool) -> dict[str, Any]:
    plan = decision.get("plan") or {}
    steps = plan.get("steps") or []
    chosen = [s for i, s in enumerate(steps) if step_indexes is None or i in step_indexes]
    lead = int(get_settings().get("reminder_lead_min") or 30)
    now = local_now()
    spec = decision.get("spec") or {}
    event = spec.get("event") or {}
    result = decision.get("result") or {}
    places = {s["subtask"]: s for s in result.get("stops", [])} if decision["decision_type"] == "errands" else {}
    created_tasks, created_events = [], []
    deadline_default = (spec.get("hard_constraints") or {}).get("deadline") or event.get("start") \
        or (spec.get("destination") or {}).get("arrive_by")
    for s in chosen:
        start = s.get("start")
        dur = int(s.get("duration_min") or 15)
        meta: dict[str, Any] = {"plan_step": True, "kind": s.get("kind")}
        stop = places.get(s["title"])
        if stop:
            meta["place"] = {k: stop["place"].get(k) for k in ("name", "address", "distance_km", "lat", "lng", "phone")}
            meta["closes"] = stop.get("closes")
        if event.get("title"):
            meta["event_title"], meta["event_start"] = event["title"], event.get("start")
        fixed = s.get("kind") == "event" and not stop and (
            decision["decision_type"] == "errands" or
            (event.get("title") and s["title"].lower().startswith(event["title"].lower())))
        if fixed:
            # A fixed appointment (the interview itself) is a calendar entry, not a to-do.
            if add_to_calendar and start:
                end = (datetime.fromisoformat(start) + timedelta(minutes=dur)).isoformat()
                created_events.append(calendar.create_event(s["title"], start, end, description=s.get("notes"),
                                                            source_decision=decision["id"]))
            continue
        reminder_at = None
        if start:
            st = datetime.fromisoformat(start)
            if st > now:
                r = st - timedelta(minutes=lead if s.get("kind") != "travel" else 15)
                reminder_at = (r if r > now else st).isoformat()
        task_deadline = None
        if start:
            task_deadline = (datetime.fromisoformat(start) + timedelta(minutes=dur)).isoformat()
        elif deadline_default:
            task_deadline = deadline_default
        t = create_task(s["title"], deadline=task_deadline, priority=s.get("priority") or "medium",
                        notes=s.get("notes"), source_decision=decision["id"], scheduled_start=start,
                        duration_min=dur, reminder_at=reminder_at, meta=meta)
        if add_to_calendar and start:
            end = (datetime.fromisoformat(start) + timedelta(minutes=dur)).isoformat()
            ev = calendar.create_event(s["title"], start, end,
                                       location=(meta.get("place") or {}).get("address"),
                                       description=s.get("notes"), source_decision=decision["id"], task_id=t["id"])
            db.update("tasks", t["id"], {"calendar_event_id": ev["id"]})
            t["calendar_event_id"] = ev["id"]
            created_events.append(ev)
        created_tasks.append(t)
    # Remember the upcoming appointment itself (doc §3: "remember that the user has an interview").
    if event.get("title") and event.get("start"):
        memory.add_memory(f"{event['title']} on {datetime.fromisoformat(event['start']):%a %d %b at %I:%M %p}",
                          kind="task", source="system", meta={"decision_id": decision["id"], "expires": event["start"]})
    return {"tasks": created_tasks, "events": created_events}
