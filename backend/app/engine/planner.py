"""Plan Generator: turns a decision into concrete, schedulable steps ("what happens next?")."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from .. import llm
from .decision import _delivery_days, metric

PLAN_SYSTEM = """You are the Plan Generator of DecisionOS. A decision has been made. Produce the concrete
next steps the user must take, scheduled sensibly before any deadline, respecting opening hours, sleep
(no steps between 23:00 and 07:00 unless unavoidable) and the current time. Never schedule purchases or
payments as automatic: they are steps for the user to do. Keep it to 2-7 steps.
Return JSON: {"summary": "one sentence", "steps": [{"title": str, "start": ISO-8601 local datetime|null,
"duration_min": int, "notes": str, "kind": "task"|"event"|"travel", "priority": "low"|"medium"|"high"|"critical"}]}"""


def _round_up(dt: datetime, minutes: int = 15) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    extra = (-dt.minute) % minutes
    return dt + timedelta(minutes=extra or minutes)


def _next_reasonable(dt: datetime) -> datetime:
    """Push into waking hours (07:00–22:30)."""
    if dt.hour >= 23 or (dt.hour == 22 and dt.minute > 30):
        dt = (dt + timedelta(days=1)).replace(hour=9, minute=0)
    elif dt.hour < 7:
        dt = dt.replace(hour=9, minute=0)
    return dt


def generate_plan(decision: dict, now: datetime) -> dict[str, Any]:
    spec, result = decision["spec"], decision["result"]
    dtype = decision["decision_type"]
    if dtype == "errands":
        return _errands_plan(spec, result)
    winner = _winner(decision)
    if llm.available() and winner is not None:
        payload = {"now": now.isoformat(), "goal": spec["goal"], "decision_type": dtype,
                   "constraints": spec["hard_constraints"], "event": spec.get("event"),
                   "chosen": {k: winner.get(k) for k in ("name", "address", "open_state", "hours", "url", "attrs")},
                   "best_offer": winner.get("best_offer"), "price": metric(winner, "price"),
                   "learning_path": result.get("learning_path")}
        out = llm.complete_json(PLAN_SYSTEM, json.dumps(payload, default=str)[:9000], max_tokens=1400)
        if isinstance(out, dict) and isinstance(out.get("steps"), list) and out["steps"]:
            steps = []
            for s in out["steps"]:
                start = None
                if s.get("start"):
                    try:
                        st = datetime.fromisoformat(s["start"])
                        start = (st.replace(tzinfo=now.tzinfo) if st.tzinfo is None else st).isoformat()
                    except ValueError:
                        start = None
                steps.append({"title": s.get("title") or "Step", "start": start,
                              "duration_min": int(s.get("duration_min") or 15), "notes": s.get("notes") or "",
                              "kind": s.get("kind") if s.get("kind") in ("task", "event", "travel") else "task",
                              "priority": s.get("priority") if s.get("priority") in ("low", "medium", "high", "critical") else "medium"})
            return {"summary": out.get("summary") or "", "steps": steps, "generated_by": "claude"}
    return _template_plan(dtype, spec, result, winner, now)


def _winner(decision: dict) -> dict | None:
    res = decision.get("result") or {}
    wid = res.get("user_choice") or res.get("winner")
    return next((c for c in decision.get("candidates") or [] if c["id"] == wid), None)


def _errands_plan(spec: dict, result: dict) -> dict[str, Any]:
    steps = []
    for item in result.get("timeline", []):
        kind = {"stop": "task", "travel": "travel", "arrive": "travel", "event": "event"}[item["kind"]]
        steps.append({"title": item["title"], "start": item["time"],
                      "duration_min": 30 if kind == "event" else 15, "notes": item.get("detail", ""),
                      "kind": kind, "priority": "high" if kind in ("task", "event") else "medium"})
    t = result.get("totals", {})
    return {"summary": f"{t.get('locations', 0)} stops · ~₹{t.get('cost', 0):,.0f} · {t.get('distance_km', 0)} km · "
                       f"{t.get('duration_min', 0)} min", "steps": steps, "generated_by": "engine"}


def _template_plan(dtype: str, spec: dict, result: dict, w: dict | None, now: datetime) -> dict[str, Any]:
    steps: list[dict] = []
    start = _next_reasonable(_round_up(now + timedelta(minutes=30)))
    deadline = spec["hard_constraints"].get("deadline")
    if w is None:
        return {"summary": "No option selected yet.", "steps": [], "generated_by": "template"}
    if dtype in ("commerce", "image"):
        offer = w.get("best_offer") or {}
        days = _delivery_days((w.get("attrs") or {}).get("delivery"), now)
        order_by = None
        if deadline and days is not None:
            order_by = datetime.fromisoformat(deadline) - timedelta(days=days + 1)
        steps = [
            {"title": f"Verify final price & seller for {w['name']}", "start": start.isoformat(), "duration_min": 15,
             "notes": f"Best seen: {offer.get('source', '')} at ₹{offer.get('price', 0):,.0f}. Check warranty and return policy.",
             "kind": "task", "priority": "medium"},
            {"title": f"Order {w['name']}", "start": (order_by if order_by and order_by > start else start + timedelta(minutes=20)).isoformat(),
             "duration_min": 10, "notes": offer.get("url") or "", "kind": "task", "priority": "high"},
            {"title": "Track delivery & inspect on arrival", "start": None, "duration_min": 10,
             "notes": "Check the item matches the listing before the return window closes.", "kind": "task", "priority": "low"},
        ]
    elif dtype == "local":
        visit = start
        steps = [
            {"title": f"Call {w['name']} to confirm", "start": start.isoformat(), "duration_min": 5,
             "notes": (w.get("attrs") or {}).get("phone") or "", "kind": "task", "priority": "medium"},
            {"title": f"Visit {w['name']}", "start": (visit + timedelta(minutes=30)).isoformat(), "duration_min": 45,
             "notes": f"{w.get('address') or ''} · {w.get('open_state') or ''}", "kind": "event", "priority": "high"},
        ]
    elif dtype == "travel":
        dep = (w.get("attrs") or {}).get("depart")
        steps = [{"title": f"Book {w['name']}", "start": start.isoformat(), "duration_min": 15,
                  "notes": f"₹{metric(w, 'price') or 0:,.0f}", "kind": "task", "priority": "high"}]
        if dep:
            try:
                d = datetime.fromisoformat(str(dep).replace(" ", "T"))
                d = d.replace(tzinfo=now.tzinfo) if d.tzinfo is None else d
                steps.append({"title": "Leave for departure", "start": (d - timedelta(minutes=120 if "flight" in (w.get("attrs") or {}).get("mode", "") else 45)).isoformat(),
                              "duration_min": 60, "notes": "", "kind": "travel", "priority": "high"})
                steps.append({"title": f"Depart: {w['name']}", "start": d.isoformat(),
                              "duration_min": int((w.get("attrs") or {}).get("duration_min") or 60), "notes": "",
                              "kind": "event", "priority": "high"})
            except ValueError:
                pass
    elif dtype == "video":
        day = start.replace(hour=19, minute=0) if start.hour < 19 else (start + timedelta(days=1)).replace(hour=19, minute=0)
        for i, item in enumerate(result.get("learning_path") or []):
            steps.append({"title": f"Day {i + 1}: {item['title']}", "start": (day + timedelta(days=i)).isoformat(),
                          "duration_min": int(max(20, (item.get("length_min") or 30) * 1.5)),
                          "notes": f"{item.get('focus', '')} — {item.get('url', '')}", "kind": "event", "priority": "medium"})
    else:
        steps = [{"title": f"Start: {w['name']}", "start": start.isoformat(), "duration_min": 60,
                  "notes": w.get("snippet") or "", "kind": "event", "priority": "medium"},
                 {"title": "Review progress and decide next step", "start": (start + timedelta(days=2)).isoformat(),
                  "duration_min": 20, "notes": "", "kind": "task", "priority": "low"}]
    return {"summary": f"Next steps for: {w['name']}", "steps": steps, "generated_by": "template"}
