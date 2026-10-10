"""DecisionOS API gateway (FastAPI).

Run:  uvicorn app.main:app --reload --port 8000   (from the backend/ folder)
"""
from __future__ import annotations

import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, llm
from .config import BASE_DIR, settings
from .engine import intent, orchestrator, planner
from .services import activity, calendar, interventions, memory, metrics, proactive, tasks
from .services.user_settings import get_settings, local_now, update_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
loop = proactive.ProactiveLoop()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    loop.start()
    yield
    loop.stop()


app = FastAPI(title="DecisionOS", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin, "http://localhost:3000",
                                                  "http://127.0.0.1:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


def _404(obj: Any, what: str = "Not found") -> Any:
    if not obj:
        raise HTTPException(404, what)
    return obj


# ------------------------------------------------------------------ models
class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    decision_id: str | None = None
    image_url: str | None = None


class DecisionIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    image_url: str | None = None


class WhatIfIn(BaseModel):
    text: str | None = None
    patch: dict | None = None


class ChooseIn(BaseModel):
    candidate_id: str


class CommitIn(BaseModel):
    steps: list[int] | None = None
    add_to_calendar: bool = True


class TaskIn(BaseModel):
    title: str
    deadline: str | None = None
    priority: str = "medium"
    notes: str | None = None
    scheduled_start: str | None = None
    duration_min: int | None = None
    project: str | None = None
    reminder_at: str | None = None


class EventIn(BaseModel):
    title: str
    start: str
    end: str
    location: str | None = None
    description: str | None = None


class MemoryIn(BaseModel):
    content: str
    kind: str | None = None


class RespondIn(BaseModel):
    action: dict


class SeenIn(BaseModel):
    ids: list[str]


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health() -> dict:
    llm_ok, llm_error = llm.status()
    return {"ok": True, "llm": llm_ok, "llm_error": llm_error,
            "model": settings.anthropic_model if llm.available() else None,
            "live_search": settings.use_live_search, "demo_mode": not settings.use_live_search,
            "google_calendar_configured": bool(settings.google_client_id),
            "google_calendar_connected": calendar.google_connected()}


@app.get("/api/serpapi/account")
def serpapi_account() -> dict:
    from .serp import client as serp_client
    return {"account": serp_client.account(), "live_search": settings.use_live_search}


# ------------------------------------------------------------------ unified entry point
@app.post("/api/ask")
def ask(body: AskIn) -> dict:
    now = local_now()
    has_active = bool(body.decision_id)
    if body.image_url:
        return {"type": "decision", "decision": orchestrator.create_decision(body.message, body.image_url)}
    c = intent.classify(body.message, now, has_active)
    kind = c.get("intent")
    if kind == "reminder":
        r = tasks.reminder_from_chat(c.get("task") or body.message, c.get("when"), now)
        when = datetime.fromisoformat(r["remind_at"])
        return {"type": "reminder", "reply": f"Got it. I'll remind you at {when:%I:%M %p, %a %d %b}."
                                             + (f" Task due {datetime.fromisoformat(r['due']):%I:%M %p, %a %d %b}." if r["due"] else ""),
                **r}
    if kind == "remember":
        m = memory.add_memory(c.get("memory") or body.message, source="explicit")
        return {"type": "memory", "reply": f"I'll remember: {m['content']}.", "memory": m}
    if kind == "forget":
        m = memory.forget(c.get("memory") or body.message)
        return {"type": "memory", "reply": f"Forgotten: {m['content']}." if m else "I couldn't find a matching memory.",
                "memory": m}
    if kind == "whatif" and body.decision_id:
        sc = orchestrator.what_if(body.decision_id, text=body.message)
        return {"type": "whatif", "scenario": sc,
                "reply": f"{sc['label']}: {sc['winner_name']}" + (" (changes the recommendation)" if sc.get("changed") else "")}
    return {"type": "decision", "decision": orchestrator.create_decision(body.message)}


# ------------------------------------------------------------------ decisions
def _summary(d: dict) -> dict:
    res = d.get("result") or {}
    exp = res.get("explanation") or {}
    return {"id": d["id"], "query": d["query"], "decision_type": d["decision_type"], "status": d["status"],
            "headline": exp.get("headline"), "options": (res.get("stats") or {}).get("candidates"),
            "created_at": d["created_at"], "updated_at": d["updated_at"]}


@app.get("/api/decisions")
def list_decisions(limit: int = 30) -> list[dict]:
    return [_summary(d) for d in db.fetch_all("SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,))]


@app.post("/api/decisions")
def new_decision(body: DecisionIn) -> dict:
    return orchestrator.create_decision(body.query, body.image_url)


@app.get("/api/decisions/{decision_id}")
def get_decision(decision_id: str) -> dict:
    return _404(orchestrator.get_decision(decision_id), "Decision not found")


@app.delete("/api/decisions/{decision_id}")
def delete_decision(decision_id: str) -> dict:
    db.delete("decisions", decision_id)
    return {"ok": True}


@app.post("/api/decisions/{decision_id}/rerun")
def rerun(decision_id: str) -> dict:
    d = _404(orchestrator.get_decision(decision_id))
    return orchestrator.create_decision(d["query"], (d.get("spec") or {}).get("image_url"))


@app.post("/api/decisions/{decision_id}/whatif")
def what_if(decision_id: str, body: WhatIfIn) -> dict:
    if not body.text and not body.patch:
        raise HTTPException(400, "Provide text or patch")
    try:
        return orchestrator.what_if(decision_id, text=body.text, patch=body.patch)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/decisions/{decision_id}/scenarios/{index}/adopt")
def adopt(decision_id: str, index: int) -> dict:
    return orchestrator.adopt_scenario(decision_id, index)


@app.post("/api/decisions/{decision_id}/choose")
def choose(decision_id: str, body: ChooseIn) -> dict:
    return orchestrator.choose_option(decision_id, body.candidate_id)


@app.post("/api/decisions/{decision_id}/accept")
def accept(decision_id: str) -> dict:
    return orchestrator.accept_decision(decision_id)


@app.post("/api/decisions/{decision_id}/plan")
def make_plan(decision_id: str) -> dict:
    d = _404(orchestrator.get_decision(decision_id))
    if d["status"] not in ("ready", "accepted", "planned"):
        raise HTTPException(409, "Decision is not ready yet")
    plan = planner.generate_plan(d, local_now())
    db.update("decisions", decision_id, {"plan": plan, "updated_at": db.now_iso()})
    return plan


@app.post("/api/decisions/{decision_id}/plan/commit")
def commit_plan(decision_id: str, body: CommitIn) -> dict:
    d = _404(orchestrator.get_decision(decision_id))
    if not d.get("plan"):
        raise HTTPException(409, "Generate a plan first")
    if d["status"] == "ready":
        d = orchestrator.accept_decision(decision_id)
    out = tasks.commit_plan(d, body.steps, body.add_to_calendar)
    db.update("decisions", decision_id, {"status": "planned", "updated_at": db.now_iso()})
    return out


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...)) -> dict:
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Only images are supported")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "Image too large (max 8 MB)")
    ext = Path(file.filename or "").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        ext = ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    url = f"{settings.public_backend_url}/uploads/{name}"
    public = not any(h in settings.public_backend_url for h in ("localhost", "127.0.0.1"))
    return {"url": url, "publicly_reachable": public,
            "note": None if public else "Google Lens needs a public URL. Expose the backend (e.g. with ngrok) and set "
                                        "PUBLIC_BACKEND_URL, or paste an image link instead."}


# ------------------------------------------------------------------ tasks & reminders
@app.get("/api/tasks")
def get_tasks(status: str | None = None) -> list[dict]:
    return tasks.list_tasks(status)


@app.post("/api/tasks")
def create_task(body: TaskIn) -> dict:
    return tasks.create_task(**body.model_dump())


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: str, patch: dict) -> dict:
    return _404(tasks.update_task(task_id, patch))


@app.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: str) -> dict:
    return _404(tasks.complete_task(task_id))


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    tasks.delete_task(task_id)
    return {"ok": True}


@app.get("/api/reminders")
def get_reminders(status: str | None = "pending") -> list[dict]:
    return tasks.list_reminders(status)


# ------------------------------------------------------------------ calendar
@app.get("/api/calendar/events")
def get_events(start: str | None = None, end: str | None = None) -> list[dict]:
    return calendar.list_events(start, end)


@app.post("/api/calendar/events")
def create_event(body: EventIn) -> dict:
    return calendar.create_event(**body.model_dump())


@app.patch("/api/calendar/events/{event_id}")
def patch_event(event_id: str, patch: dict) -> dict:
    return _404(calendar.update_event(event_id, patch))


@app.delete("/api/calendar/events/{event_id}")
def delete_event(event_id: str) -> dict:
    calendar.delete_event(event_id)
    return {"ok": True}


@app.get("/api/calendar/feed.ics")
def ics_feed() -> PlainTextResponse:
    return PlainTextResponse(calendar.ics_feed(), media_type="text/calendar",
                             headers={"Content-Disposition": "attachment; filename=decisionos.ics"})


@app.get("/api/calendar/google/connect")
def google_connect() -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(400, "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env first")
    state = secrets.token_urlsafe(16)
    db.upsert("settings", {"key": "oauth_state", "value": {"state": state}}, key="key")
    return RedirectResponse(calendar.google_auth_url(state))


@app.get("/api/calendar/google/callback")
def google_callback(code: str, state: str) -> RedirectResponse:
    saved = (db.fetch_one("SELECT value FROM settings WHERE key='oauth_state'") or {}).get("value") or {}
    if not saved or saved.get("state") != state:
        raise HTTPException(400, "Invalid OAuth state")
    calendar.google_exchange_code(code)
    return RedirectResponse(f"{settings.frontend_origin}/calendar?connected=google")


@app.post("/api/calendar/google/disconnect")
def google_disconnect() -> dict:
    calendar.google_disconnect()
    return {"ok": True}


# ------------------------------------------------------------------ memory
@app.get("/api/memories")
def get_memories(status: str | None = None) -> list[dict]:
    return memory.list_memories(status)


@app.post("/api/memories")
def add_memory(body: MemoryIn) -> dict:
    return memory.add_memory(body.content, kind=body.kind, source="explicit")


@app.patch("/api/memories/{mem_id}")
def patch_memory(mem_id: str, patch: dict) -> dict:
    return _404(memory.edit_memory(mem_id, patch))


@app.delete("/api/memories/{mem_id}")
def delete_memory(mem_id: str) -> dict:
    memory.delete_memory(mem_id)
    return {"ok": True}


# ------------------------------------------------------------------ settings
@app.get("/api/settings")
def read_settings() -> dict:
    return get_settings()


@app.patch("/api/settings")
def patch_settings(patch: dict) -> dict:
    return update_settings(patch)


@app.get("/api/geocode")
def geocode(q: str) -> list[dict]:
    """Resolve a typed place ("SRM hostel, Kattankulathur") to coordinates via the Maps capability."""
    from .serp import capabilities as cap
    s = get_settings()
    home = s.get("home") or {}
    res = cap.find_local_places(q, home.get("lat"), home.get("lng"))
    return [{"label": o["name"], "address": o.get("address"), "lat": o["lat"], "lng": o["lng"]}
            for o in res["observations"] if o.get("lat") is not None][:5]


# ------------------------------------------------------------------ workspace activity
@app.post("/api/activity")
def post_activity(payload: dict, x_agent_token: str | None = Header(default=None)) -> dict:
    if settings.agent_token and x_agent_token != settings.agent_token:
        raise HTTPException(401, "Bad agent token")
    return activity.ingest(payload)


@app.get("/api/activity/status")
def activity_status() -> dict:
    return activity.status()


@app.delete("/api/activity")
def clear_activity() -> dict:
    activity.clear_activity()
    return {"ok": True}


# ------------------------------------------------------------------ interventions
@app.get("/api/interventions")
def get_interventions(status: str | None = None, unseen: bool = False, limit: int = 50) -> list[dict]:
    return interventions.list_interventions(status, unseen, limit)


@app.post("/api/interventions/seen")
def seen(body: SeenIn) -> dict:
    interventions.mark_seen(body.ids)
    return {"ok": True}


@app.post("/api/interventions/{intervention_id}/respond")
def respond(intervention_id: str, body: RespondIn) -> dict:
    try:
        return proactive.respond(intervention_id, body.action)
    except KeyError:
        raise HTTPException(404, "Intervention not found")


@app.post("/api/proactive/tick")
def tick() -> dict:
    proactive.tick()
    return {"ok": True}


@app.post("/api/demo/simulate-idle")
def simulate_idle(minutes: int = 20) -> dict:
    """Demo helper: pretend the workspace agent reported the user idle (bypasses the opt-in only for this event)."""
    last = db.fetch_one("SELECT project FROM activity_events WHERE project IS NOT NULL ORDER BY ts DESC LIMIT 1") or {}
    db.insert("events", {"id": db.new_id("ev"), "type": "USER_IDLE",
                         "payload": {"idle_min": minutes, "last_project": last.get("project"), "simulated": True},
                         "dedupe_key": f"sim-idle:{db.now_iso()}", "processed": 0, "created_at": db.now_iso()})
    proactive.tick()
    return {"ok": True, "latest": interventions.list_interventions(limit=1)}


# ------------------------------------------------------------------ dashboard
@app.get("/api/dashboard")
def dashboard() -> dict:
    now = local_now()
    s = get_settings()
    open_tasks = tasks.list_tasks("open")
    end_of_day = now.replace(hour=23, minute=59)

    def at(t: dict) -> datetime | None:
        v = t.get("scheduled_start") or t.get("deadline")
        return datetime.fromisoformat(v) if v else None

    today_tasks = [t for t in open_tasks if at(t) and at(t) <= end_of_day]
    approaching = [t for t in open_tasks if t.get("deadline") and now <= datetime.fromisoformat(t["deadline"]) <= now + timedelta(hours=24)]
    events_today = calendar.list_events(now.replace(hour=0, minute=0).isoformat(), end_of_day.isoformat())
    upcoming = sorted(
        [{"time": at(t).isoformat(), "title": t["title"], "kind": "task", "id": t["id"]} for t in open_tasks if at(t) and at(t) >= now - timedelta(minutes=30)] +
        [{"time": e["start"], "title": e["title"], "kind": "event", "id": e["id"]} for e in calendar.list_events(now.isoformat())
         if not e.get("task_id")], key=lambda x: x["time"])[:6]
    forgotten = [t for t in open_tasks if (t.get("deadline") and datetime.fromisoformat(t["deadline"]) < now)
                 or (t["status"] == "pending" and t.get("scheduled_start") and datetime.fromisoformat(t["scheduled_start"]) < now - timedelta(minutes=30))]
    in_progress = [_summary(d) for d in db.fetch_all(
        "SELECT * FROM decisions WHERE status IN ('researching','ready','accepted') ORDER BY updated_at DESC LIMIT 4")]
    hour = now.hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    return {"greeting": f"{greeting}{', ' + s['name'] if s.get('name') else ''}", "now": now.isoformat(),
            "mode": s.get("mode"), "today": {"tasks_remaining": len(today_tasks), "deadlines_approaching": len(approaching),
                                             "events": len(events_today)},
            "up_next": upcoming, "decisions_in_progress": in_progress, "forgotten": forgotten[:5],
            "proposed_memories": memory.list_memories("proposed"), "metrics": metrics.summary(),
            "activity": activity.status(), "health": health()}


@app.get("/api/metrics")
def get_metrics() -> dict:
    return metrics.summary()


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    from fastapi.responses import JSONResponse
    logging.getLogger("decisionos").exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)[:300]})
