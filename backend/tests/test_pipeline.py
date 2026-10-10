"""End-to-end tests of the DecisionOS engine on demo data (no API keys, no network).

Run from backend/:   python -m pytest -q      (or)   python tests/test_pipeline.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""          # exercise the heuristic fallbacks

from app import db  # noqa: E402
from app.engine import decision as dec  # noqa: E402
from app.engine import evidence, orchestrator, planner  # noqa: E402
from app.services import activity, interventions, memory, proactive, tasks  # noqa: E402
from app.services import user_settings as us  # noqa: E402

db.init_db()
us.update_settings({"home": {"label": "Hostel", "lat": 13.0, "lng": 80.22}, "mode": "assistant",
                    "quiet_hours": {"enabled": False}})


def test_same_product_matching():
    assert evidence.same_product("Sony WH-CH720N Wireless ANC Headphones", "Sony WH-CH720N Wireless Headphones Black")
    assert not evidence.same_product("Sony WH-CH720N Headphones", "Sony WH-1000XM5 Headphones")


def test_commerce_decision_respects_budget():
    d = orchestrator.create_decision("I need a laptop for coding under ₹70,000, preferably lightweight", background=False)
    assert d["status"] == "ready", d.get("error")
    r = d["result"]
    by_id = {c["id"]: c for c in d["candidates"]}
    assert dec.metric(by_id[r["winner"]], "price") <= 70000
    assert r["eliminated_summary"].get("over_budget", 0) >= 1
    assert r["explanation"]["headline"]
    assert any(c["key"].startswith("j:") for c in d["spec"]["criteria"])


def test_what_if_budget_changes_constraints():
    d = orchestrator.create_decision("headphones under ₹2,000", background=False)
    sc = orchestrator.what_if(d["id"], "What if my budget is ₹8,000?")
    assert sc["hard_constraints"]["budget_max"] == 8000
    assert orchestrator.get_decision(d["id"])["result"]["scenarios"]


def test_errands_plan_and_commit():
    d = orchestrator.create_decision("I need to buy a USB drive, print my assignment, get passport photos and reach "
                                     "college by 4 PM. I have ₹1,000.", background=False)
    r = d["result"]
    assert d["decision_type"] == "errands"
    assert len(r["stops"]) == 3 and r["totals"]["cost"] > 0
    assert r["timeline"][0]["title"].startswith("Leave")
    plan = planner.generate_plan(d, us.local_now())
    db.update("decisions", d["id"], {"plan": plan})
    out = tasks.commit_plan(orchestrator.get_decision(d["id"]), None, True)
    assert out["tasks"] and out["events"]


def test_local_video_travel_knowledge_run():
    for q, t in [("Where should I repair my laptop?", "local"), ("I'm trying to learn Docker. What should I watch?", "video"),
                 ("Chennai to Bangalore this weekend under ₹6,000", "travel"),
                 ("I want to build a project about EV charging. What problem should I work on?", "knowledge")]:
        d = orchestrator.create_decision(q, background=False)
        assert d["status"] == "ready", (q, d.get("error"))
        assert d["decision_type"] == t, (q, d["decision_type"])
    assert d["result"]["ranking"]


def test_image_decision_identifies_product():
    d = orchestrator.create_decision("what is this?", image_url="https://example.com/shoe.jpg", background=False)
    assert d["result"]["identified_as"]
    assert all(evidence.same_product(c["name"], d["result"]["identified_as"]) for c in d["candidates"])


def test_reminder_and_proactive_loop():
    now = us.local_now()
    r = tasks.reminder_from_chat("submit the assignment", (now + timedelta(minutes=45)).isoformat(), now)
    db.execute("UPDATE reminders SET remind_at=? WHERE id IN (SELECT id FROM reminders WHERE task_id=?)",
               ((now - timedelta(minutes=1)).isoformat(), r["task"]["id"]))
    proactive.tick()
    rows = interventions.list_interventions(limit=20)
    assert any(i["event_type"] == "REMINDER_DUE" and "submit the assignment" in i["message"] for i in rows)


def test_quiet_mode_suppresses_low_priority():
    us.update_settings({"mode": "focus"})
    row = interventions.create("BREAK_SUGGESTED", "Break?", "Take a break", 0.35, 0.6, 0.8)
    assert row["status"] == "suppressed" and "Focus" in row["reason"]
    us.update_settings({"mode": "assistant"})


def test_workspace_idle_requires_opt_in_and_suggests():
    us.update_settings({"workspace": {"enabled": False}})
    assert activity.ingest({"app": "Code", "idle_seconds": 10})["accepted"] is False
    us.update_settings({"workspace": {"enabled": True, "idle_threshold_min": 15}})
    activity.ingest({"app": "Code", "project": "EVRoute", "idle_seconds": 5, "keystrokes": "nope"})
    activity.ingest({"app": "Code", "project": "EVRoute", "idle_seconds": 1200})
    row = db.fetch_one("SELECT * FROM activity_events ORDER BY ts DESC LIMIT 1")
    assert "keystrokes" not in row
    proactive.tick()
    assert db.fetch_one("SELECT COUNT(*) AS n FROM events WHERE type='USER_IDLE'")["n"] >= 1


def test_inferred_memory_is_only_proposed():
    for q in ["usb drive under 600", "phone under 20000", "headphones under 3000"]:
        orchestrator.accept_decision(orchestrator.create_decision(q, background=False)["id"])
    proposed = memory.list_memories("proposed")
    assert proposed, "repeated behaviour should produce a proposal"
    assert all(m["source"] == "inferred" for m in proposed)
    assert not any(m["source"] == "inferred" for m in memory.list_memories("active"))


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f()
        print("✓", f.__name__)
    print(f"{len(fns)} passed")
