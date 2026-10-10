"""Proactive agent loop (doc §40-41): event-driven, no LLM in the loop.

Every tick (default 30 s) it:
  1. detects time-based events (TASK_DUE_SOON, TASK_OVERDUE, CALENDAR_EVENT_APPROACHING, REMINDER_DUE,
     QUIET_HOURS_STARTED/ENDED, SEARCH_RESULT_EXPIRED, PROJECT_ABANDONED, BREAK_SUGGESTED, PLANNED_TASK_NOT_STARTED),
     deduplicated by key so each fires once;
  2. turns unprocessed events (including USER_IDLE / USER_RETURNED from the workspace agent) into
     context-aware interventions, which the intervention policy delivers or suppresses.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from .. import db
from ..config import settings as cfg
from . import activity, interventions
from .user_settings import get_settings, in_quiet_hours, local_now, tz

log = logging.getLogger("decisionos.proactive")


def _emit(etype: str, payload: dict, dedupe: str) -> None:
    db.insert("events", {"id": db.new_id("ev"), "type": etype, "payload": payload, "dedupe_key": dedupe,
                         "processed": 0, "created_at": db.now_iso()}, or_ignore=True)


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    d = datetime.fromisoformat(iso)
    return d.replace(tzinfo=tz()) if d.tzinfo is None else d


def _fmt_time(d: datetime, now: datetime) -> str:
    d = d.astimezone(now.tzinfo)
    day = "today" if d.date() == now.date() else "tomorrow" if d.date() == (now + timedelta(days=1)).date() \
        else d.strftime("%a %d %b")
    return f"{d.strftime('%I:%M %p').lstrip('0')} {day}"


# ------------------------------------------------------------------ 1. detect
def detect(now: datetime) -> None:
    s = get_settings()
    open_tasks = db.fetch_all("SELECT * FROM tasks WHERE status IN ('pending','in_progress')")
    for t in open_tasks:
        dl = _dt(t["deadline"])
        if dl and now < dl <= now + timedelta(minutes=60):
            _emit("TASK_DUE_SOON", {"task_id": t["id"]}, f"due_soon:{t['id']}:{t['deadline']}")
        elif dl and dl < now:
            _emit("TASK_OVERDUE", {"task_id": t["id"]}, f"overdue:{t['id']}:{now:%Y%m%d}")
        st = _dt(t["scheduled_start"])
        if st and t["status"] == "pending" and st + timedelta(minutes=20) <= now <= st + timedelta(minutes=(t["duration_min"] or 30) + 20):
            _emit("PLANNED_TASK_NOT_STARTED", {"task_id": t["id"]}, f"not_started:{t['id']}:{t['scheduled_start']}")
    for r in db.fetch_all("SELECT * FROM reminders WHERE status='pending'"):
        if _dt(r["remind_at"]) <= now:
            db.update("reminders", r["id"], {"status": "fired"})
            _emit("REMINDER_DUE", {"reminder_id": r["id"], "task_id": r["task_id"], "message": r["message"]},
                  f"reminder:{r['id']}")
    for e in db.fetch_all("SELECT * FROM calendar_events"):
        st = _dt(e["start"])
        if st and now < st <= now + timedelta(minutes=30) and not e["task_id"]:
            _emit("CALENDAR_EVENT_APPROACHING", {"event_id": e["id"]}, f"cal:{e['id']}:{e['start']}")
    # quiet hours transitions
    state = (db.fetch_one("SELECT value FROM settings WHERE key='proactive_state'") or {}).get("value") or {}
    q = in_quiet_hours(now, s)
    if state.get("quiet") is not None and state.get("quiet") != q:
        _emit("QUIET_HOURS_STARTED" if q else "QUIET_HOURS_ENDED", {}, f"quiet:{q}:{now:%Y%m%d%H}")
    state["quiet"] = q
    db.upsert("settings", {"key": "proactive_state", "value": state}, key="key")
    # stale recommendations
    day_ago = (now - timedelta(hours=24)).isoformat()
    for d in db.fetch_all("SELECT id, query FROM decisions WHERE status='ready' AND updated_at<?", (day_ago,)):
        _emit("SEARCH_RESULT_EXPIRED", {"decision_id": d["id"], "query": d["query"]}, f"expired:{d['id']}")
    # abandoned projects (only meaningful with workspace awareness)
    week_ago = (now - timedelta(days=3)).isoformat()
    for p in db.fetch_all("SELECT * FROM projects WHERE last_active_at<?", (week_ago,)):
        n = db.fetch_one("SELECT COUNT(*) AS n FROM tasks WHERE project=? AND status!='done'", (p["name"],))["n"]
        if n:
            _emit("PROJECT_ABANDONED", {"project": p["name"], "open_tasks": n}, f"abandoned:{p['name']}:{now:%Y%W}")
    # break suggestion
    ws = s.get("workspace") or {}
    if ws.get("enabled") and not ws.get("paused"):
        streak, start = activity.active_streak_minutes()
        if streak >= int(ws.get("break_after_min") or 120):
            _emit("BREAK_SUGGESTED", {"minutes": round(streak)}, f"break:{start}")


# ------------------------------------------------------------------ 2. interpret
def _task_context(t: dict, now: datetime) -> str:
    """Context clause(s) of doc §19, e.g. ' before your interview at 10:00 AM tomorrow. Bata Store closes at 9 PM and is 1.6 km away.'"""
    meta = t.get("meta") or {}
    out = ""
    if meta.get("event_title") and meta.get("event_start"):
        out += f" before your {meta['event_title'].lower()} at {_fmt_time(_dt(meta['event_start']), now)}"
    out += "."
    place = meta.get("place") or {}
    if place.get("name"):
        bits = []
        if meta.get("closes"):
            h, m = map(int, meta["closes"].split(":"))
            bits.append(f"closes at {datetime(2000, 1, 1, h % 24, m).strftime('%I:%M %p').lstrip('0')}")
        if place.get("distance_km") is not None:
            bits.append(f"is {place['distance_km']:.1f} km away")
        if bits:
            out += f" {place['name']} {' and '.join(bits)}."
    return out


def _idle_suggestion(payload: dict, now: datetime, s: dict) -> dict | None:
    """Priority hierarchy of doc §23."""
    open_tasks = db.fetch_all("SELECT * FROM tasks WHERE status IN ('pending','in_progress')")
    def due(t):
        return _dt(t["deadline"])
    # 1. critical deadline (<2h)
    crit = sorted([t for t in open_tasks if due(t) and now < due(t) <= now + timedelta(hours=2)], key=due)
    if crit:
        t = crit[0]
        return {"title": f"Due soon: {t['title']}", "urgency": 0.95, "relevance": 0.9, "task": t,
                "message": f"You've been idle for {payload.get('idle_min')} min. “{t['title']}” is due at "
                           f"{_fmt_time(due(t), now)}{_task_context(t, now)}"}
    # 2. time-sensitive (due today)
    today = [t for t in open_tasks if due(t) and due(t).astimezone(now.tzinfo).date() == now.date() and due(t) > now]
    if today:
        t = sorted(today, key=due)[0]
        return {"title": f"Still to do today: {t['title']}", "urgency": 0.75, "relevance": 0.8, "task": t,
                "message": f"You planned to finish “{t['title']}” today (due {_fmt_time(due(t), now)}). Want to do it now?"}
    # 3. explicitly planned now
    planned = [t for t in open_tasks if _dt(t["scheduled_start"]) and abs((_dt(t["scheduled_start"]) - now).total_seconds()) < 1800]
    if planned:
        t = planned[0]
        dur = t.get("duration_min") or 30
        return {"title": f"Planned now: {t['title']}", "urgency": 0.7, "relevance": 0.85, "task": t,
                "message": f"You haven't started “{t['title']}” yet. You planned {dur} minutes for this. Continue?"}
    # 4. unfinished current project
    proj = payload.get("last_project")
    if proj:
        ptasks = [t for t in open_tasks if (t.get("project") or "").lower() == proj.lower()]
        if ptasks:
            t = ptasks[0]
            return {"title": f"Back to {proj}?", "urgency": 0.55, "relevance": 0.8, "task": t, "project": proj,
                    "message": f"You were working on {proj} earlier. You still had “{t['title']}” pending."}
        return {"title": f"Back to {proj}?", "urgency": 0.4, "relevance": 0.6, "project": proj,
                "message": f"You were working on {proj} before you stepped away. Pick up where you left off?"}
    # 5. recently abandoned task
    stale = [t for t in open_tasks if t["status"] == "in_progress"]
    if stale:
        t = stale[0]
        return {"title": f"Unfinished: {t['title']}", "urgency": 0.45, "relevance": 0.7, "task": t,
                "message": f"You started “{t['title']}” but haven't finished it. Want to continue?"}
    # 6. known interests (explicit opt-in only)
    if (s.get("workspace") or {}).get("suggest_interests"):
        m = db.fetch_one("SELECT * FROM memories WHERE status='active' AND kind IN ('interest','habit') "
                         "ORDER BY RANDOM() LIMIT 1")
        if m:
            return {"title": "Something you enjoy", "urgency": 0.3, "relevance": 0.6,
                    "message": f"Nothing urgent right now. You mentioned: “{m['content']}”. Want to spend some time on it?"}
    return None


def _actions_for_task(t: dict | None, project: str | None = None) -> list[dict]:
    acts: list[dict] = []
    if t:
        acts += [{"type": "start_task", "label": "Start now", "task_id": t["id"]},
                 {"type": "complete_task", "label": "Mark done", "task_id": t["id"]},
                 {"type": "snooze", "label": "Snooze 15 min", "task_id": t["id"], "minutes": 15}]
        if t.get("source_decision"):
            acts.append({"type": "open_decision", "label": "Reopen decision", "decision_id": t["source_decision"]})
    if project:
        p = db.fetch_one("SELECT * FROM projects WHERE name=?", (project,))
        if p and p.get("path"):
            acts.append({"type": "open_project", "label": f"Open {project} in VS Code", "path": p["path"]})
    acts.append({"type": "dismiss", "label": "Dismiss"})
    return acts


def interpret(ev: dict, now: datetime) -> None:
    s = get_settings()
    p = ev.get("payload") or {}
    etype = ev["type"]
    task = db.fetch_one("SELECT * FROM tasks WHERE id=?", (p["task_id"],)) if p.get("task_id") else None
    if task and task["status"] in ("done", "cancelled"):
        return
    if etype == "REMINDER_DUE":
        if task:
            dl = _dt(task["deadline"])
            when = f" (due {_fmt_time(dl, now)})" if dl else ""
            urgency = 0.9 if dl and dl - now <= timedelta(hours=1) else 0.7
            msg = f"You planned to {task['title'][0].lower() + task['title'][1:]}{when}{_task_context(task, now)}"
            msg += " You haven't marked it complete yet."
            interventions.create(etype, task["title"], msg, urgency, 0.9, 0.95, _actions_for_task(task))
        else:
            interventions.create(etype, "Reminder", p.get("message") or "Reminder", 0.7, 0.8, 0.95,
                                 [{"type": "dismiss", "label": "Dismiss"}])
    elif etype == "TASK_DUE_SOON" and task:
        dl = _dt(task["deadline"])
        mins = max(1, int((dl - now).total_seconds() // 60))
        interventions.create(etype, f"Due in {mins} min: {task['title']}",
                             f"“{task['title']}” is due at {_fmt_time(dl, now)}{_task_context(task, now)}",
                             0.9 if task["priority"] in ("high", "critical") else 0.75, 0.9, 0.95,
                             _actions_for_task(task))
    elif etype == "TASK_OVERDUE" and task:
        interventions.create(etype, f"Overdue: {task['title']}",
                             f"“{task['title']}” was due {_fmt_time(_dt(task['deadline']), now)}. "
                             "Reschedule it or mark it done?", 0.6, 0.8, 0.9, _actions_for_task(task))
    elif etype == "PLANNED_TASK_NOT_STARTED" and task:
        st = activity.status()
        if st["agent_online"] and (st["idle_min"] or 0) < 5:
            msg = f"You planned to start “{task['title']}” at {_fmt_time(_dt(task['scheduled_start']), now)}. " \
                  f"You're currently in {st['app'] or 'another app'}. Want to switch to it?"
        else:
            msg = f"“{task['title']}” was planned for {_fmt_time(_dt(task['scheduled_start']), now)}. Want to start it now?"
        interventions.create(etype, f"Planned: {task['title']}", msg, 0.65, 0.85, 0.8,
                             _actions_for_task(task, task.get("project")))
    elif etype == "CALENDAR_EVENT_APPROACHING":
        e = db.fetch_one("SELECT * FROM calendar_events WHERE id=?", (p["event_id"],))
        if e:
            st = _dt(e["start"])
            interventions.create(etype, f"Starting soon: {e['title']}",
                                 f"{e['title']} starts at {_fmt_time(st, now)}"
                                 + (f" at {e['location']}." if e.get("location") else "."), 0.8, 0.85, 0.95,
                                 [{"type": "dismiss", "label": "OK"}])
    elif etype == "USER_IDLE":
        if in_quiet_hours(now, s):
            return
        sug = _idle_suggestion(p, now, s)
        if sug:
            interventions.create(etype, sug["title"], sug["message"], sug["urgency"], sug["relevance"], 0.7,
                                 _actions_for_task(sug.get("task"), sug.get("project")))
    elif etype == "BREAK_SUGGESTED":
        interventions.create(etype, "Time for a break?",
                             f"You've been working for {p['minutes'] // 60} h {p['minutes'] % 60} min. Want a 10-minute break?",
                             0.35, 0.6, 0.8, [{"type": "snooze", "label": "Later", "minutes": 30},
                                              {"type": "dismiss", "label": "Dismiss"}])
    elif etype == "SEARCH_RESULT_EXPIRED":
        interventions.create(etype, "Prices may have changed",
                             f"Your recommendation for “{p['query']}” is over a day old. Refresh it before acting?",
                             0.3, 0.6, 0.9, [{"type": "refresh_decision", "label": "Refresh", "decision_id": p["decision_id"]},
                                             {"type": "dismiss", "label": "Dismiss"}])
    elif etype == "PROJECT_ABANDONED":
        interventions.create(etype, f"{p['project']} has gone quiet",
                             f"You haven't worked on {p['project']} for a few days and it has {p['open_tasks']} open task(s).",
                             0.3, 0.6, 0.7, _actions_for_task(None, p["project"]))
    elif etype == "DEADLINE_CHANGED" and task:
        db.execute("DELETE FROM events WHERE dedupe_key LIKE ?", (f"due_soon:{task['id']}:%",))
    # USER_RETURNED / QUIET_HOURS_* are recorded for the activity log; no notification needed.


def tick() -> None:
    now = local_now()
    detect(now)
    for ev in db.fetch_all("SELECT * FROM events WHERE processed=0 ORDER BY created_at LIMIT 50"):
        try:
            interpret(ev, now)
        except Exception as exc:
            log.warning("event %s failed: %s", ev["type"], exc)
        db.update("events", ev["id"], {"processed": 1})


class ProactiveLoop:
    def __init__(self, interval: int | None = None):
        self.interval = interval or cfg.proactive_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="proactive-loop")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                tick()
            except Exception as exc:
                log.error("proactive tick failed: %s", exc)
            self._stop.wait(self.interval)


def respond(intervention_id: str, action: dict[str, Any]) -> dict[str, Any]:
    """Handle the user's response to an intervention."""
    from . import memory, tasks
    row = db.fetch_one("SELECT * FROM interventions WHERE id=?", (intervention_id,))
    if not row:
        raise KeyError(intervention_id)
    kind = action.get("type")
    out: dict[str, Any] = {"ok": True}
    if kind == "complete_task":
        tasks.complete_task(action["task_id"])
    elif kind == "start_task":
        tasks.update_task(action["task_id"], {"status": "in_progress"})
    elif kind == "snooze":
        at = local_now() + timedelta(minutes=int(action.get("minutes") or 15))
        tasks.add_reminder(action.get("task_id"), at.isoformat(), row["message"])
    elif kind == "confirm_memory":
        memory.edit_memory(action["memory_id"], {"status": "active"})
    elif kind == "reject_memory":
        memory.edit_memory(action["memory_id"], {"status": "rejected"})
    elif kind == "refresh_decision":
        from ..engine import orchestrator
        old = orchestrator.get_decision(action["decision_id"])
        if old:
            out["decision"] = orchestrator.create_decision(old["query"], (old.get("spec") or {}).get("image_url"))
    db.update("interventions", intervention_id,
              {"response": "dismissed" if kind == "dismiss" else "snoozed" if kind == "snooze" else "acted", "seen": 1})
    return out
