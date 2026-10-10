"""Routing tests: does DecisionOS work out the right job for a query, call the right tools, and avoid
unnecessary ones? Runs on the rule-based planner + demo data (no API keys, no network).

Run from backend/:   python -m pytest -q tests/test_routing.py   (or)   python tests/test_routing.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "routing.db")
os.environ["DEMO_MODE"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""

from app import db  # noqa: E402
from app.engine import intent, orchestrator, research  # noqa: E402
from app.serp import registry  # noqa: E402

db.init_db()
NOW = datetime(2026, 10, 10, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
CTX = {"location_label": "Chennai", "location": {"lat": 13.08, "lng": 80.27}}

# (query, expected decision type, tools that must be planned, tools that must NOT be planned)
CASES = [
    ("Laptop for coding under ₹70K, lightweight", "commerce", [], []),
    ("Where should I repair my laptop?", "local", [], []),
    ("Chennai to Bangalore this weekend under ₹3,000", "travel", [], []),
    ("I'm learning Docker, what should I watch?", "video", [], []),
    ("I need to print my resume, buy formal shoes and reach the office by 9:30 AM", "errands", [], []),
    ("suggest me a 3 days trip to any place under 600km from chennai and budget is 8k", "trip",
     ["web_search", "stays", "tripadvisor"], ["product_search", "flights", "finance"]),
    ("plan a 2 night trip to pondicherry from chennai", "trip", ["stays", "tripadvisor"], ["web_search", "product_search"]),
    ("what concerts are happening in chennai this weekend", "general", ["events"], ["product_search", "stays", "finance"]),
    ("TCS share price", "general", ["finance", "news_search"], ["product_search", "stays", "events"]),
    ("nifty 50 today", "general", ["finance"], ["product_search", "stays"]),
    ("best apps for learning spanish", "general", ["apps"], ["videos", "product_search", "stays"]),
    ("is pickleball trending in india", "general", ["trends"], ["product_search", "stays", "finance"]),
    ("show me pictures of tsomgo lake", "general", ["images"], ["product_search", "stays", "news_search"]),
    ("data analyst internships in bangalore", "general", ["jobs"], ["product_search", "stays", "images"]),
    ("cheap hotels near MG Marg Gangtok", "general", ["stays"], ["product_search", "finance", "images"]),
    ("best momos near MG Marg Gangtok", "general", ["local_places"], ["stays", "finance", "images"]),
    ("latest news on electric vehicles in india", "general", ["news_search"], ["stays", "finance", "images"]),
    ("what is Gangtok famous for", "general", ["web_search"], ["stays", "flights", "finance", "images", "events"]),
    ("how is the stock market today", "general", ["markets"], ["finance", "product_search", "stays"]),
    ("whats trending today", "general", ["trending_now"], ["trends", "product_search", "stays"]),
    ("reviews of roll house mg marg gangtok", "general", ["place_reviews"], ["product_search", "stays", "finance"]),
    ("how do I apply for a passport in india", "general", ["ai_answer", "web_search"], ["stays", "finance", "events", "jobs"]),
]


def _plan(query: str) -> tuple[str, list[str]]:
    spec = intent.normalise_spec(intent.heuristic_spec(query, NOW, CTX), query, NOW, CTX)
    dtype = spec["decision_type"]
    if dtype == "general":
        plan = research.rule_plan(query, spec, CTX)
    elif dtype == "trip":
        from app.engine import trip
        plan = trip.make_plan(spec["trip"], NOW)
    else:
        return dtype, []
    return dtype, [t["tool"] for t in plan["tasks"]]


def test_routing_table():
    failures = []
    for query, dtype, must, must_not in CASES:
        got_type, tools = _plan(query)
        if got_type != dtype:
            failures.append(f"{query!r}: type {got_type}, expected {dtype}")
            continue
        missing = [t for t in must if t not in tools]
        extra = [t for t in must_not if t in tools]
        if missing or extra:
            failures.append(f"{query!r}: tools {tools} (missing {missing}, unnecessary {extra})")
    assert not failures, "\n".join(failures)


def test_planned_tools_are_registered_and_valid():
    for query, *_ in CASES:
        dtype, _ = _plan(query)
        if dtype != "general":
            continue
        plan = research.rule_plan(query, {}, CTX)
        assert len(plan["tasks"]) <= research.MAX_TASKS
        for t in plan["tasks"]:
            args, err = registry.validate(t["tool"], t["args"])
            assert not err, f"{query!r}: {err}"


def test_claude_plan_is_validated():
    tasks, rejected = research._validated([
        {"tool": "events", "args": {"q": "events in Chennai", "when": "weekend"}},
        {"tool": "hack_the_planet", "args": {"q": "x"}},           # unknown tool -> rejected
        {"tool": "finance", "args": {}},                            # missing required arg -> rejected
        {"tool": "events", "args": {"q": "events in Chennai", "when": "weekend"}},   # duplicate -> dropped
    ])
    assert [t["tool"] for t in tasks] == ["events"]
    assert len(rejected) == 2


def test_trip_plan_runs_and_respects_budget():
    d = orchestrator.create_decision("suggest a 3 day trip under 600km from chennai, budget 8000", background=False)
    assert d["status"] == "ready", d.get("error")
    r = d["result"]
    assert d["decision_type"] == "trip" and r["options"]
    assert d["spec"]["clarifying_question"]                     # no dates given -> asks
    for o in r["options"]:
        if not o["eliminated"]:
            assert o["total"] <= 8000
            assert o["distance_km"] is None or o["distance_km"] <= 660
    if r["winner"]:
        assert r["itinerary"] and len(r["itinerary"]) == 3
        assert r["winner"] == r["options"][0]["name"]


def test_research_answer_cites_evidence():
    d = orchestrator.create_decision("what concerts are happening in chennai this weekend", background=False)
    assert d["status"] == "ready", d.get("error")
    r = d["result"]
    plan = d["research"]["task_plan"]
    tools = [t["tool"] for t in plan["tasks"]]
    assert tools[0] == "ai_answer" and "events" in tools
    assert all(t["status"] in ("done", "fallback", "empty", "failed") for t in plan["tasks"])
    events = next(sec for sec in r["sections"] if sec["tool"] == "events")
    assert events["items"] and all(it["status"] == "event listing" for it in events["items"])
    # no Claude in tests -> the written answer comes from Google AI Mode, with its sources listed
    assert r["answer"]["generated_by"] == "google_ai_mode" and r["answer"]["sources"]


def test_trip_uses_serpapi_for_distance_fares_and_itinerary():
    d = orchestrator.create_decision("plan a 3 day trip from chennai to kodaikanal", background=False)
    r = d["result"]
    best = r["options"][0]
    assert best["distance_basis"] == "Google Maps driving route"
    assert "Google AI Mode" in (best.get("transport_basis") or "")
    assert r["itinerary_by"] == "google_ai_mode" and len(r["itinerary"]) == 3
    assert any(t["tool"] == "ai_answer" for t in d["research"]["task_plan"]["tasks"])


def test_backup_chains_are_registered():
    for name in registry.TOOLS:
        for fb in registry.fallbacks(name):
            assert fb in registry.TOOLS, f"{name} -> unknown fallback {fb}"
    assert registry.fallbacks("web_search") == ("web_search_alt", "web_search_more")
    assert registry.fallbacks("ai_answer")[0] == "ai_answer_alt"


def test_trip_shows_guest_reviews_for_recommended_stay():
    d = orchestrator.create_decision("plan a 3 day trip from chennai to ooty", background=False)
    best = d["result"]["options"][0]
    assert best["stay"] and best["stay"].get("guest_reviews")


def test_travel_ground_options_from_ai_mode():
    from app.engine import synthesis
    obs, method = synthesis._ground_from_ai_mode({"from": "Chennai", "to": "Bangalore"})
    assert method == "google_ai_mode" and {o["attrs"]["mode"] for o in obs} == {"train", "bus"}
    assert all(o["price"] and o["attrs"]["duration_min"] for o in obs)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("all routing tests passed")
