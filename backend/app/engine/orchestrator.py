"""Decision Orchestrator — the agent loop of doc §39:

UNDERSTAND -> PLAN SEARCHES -> SEARCH -> COLLECT EVIDENCE -> COMPARE -> DECIDE -> EXPLAIN
(-> PLAN / SCHEDULE / REMEMBER happen on user confirmation, see services/).

Each stage is logged into decision.research.steps so the UI can show live progress and the
"See evidence" view can show exactly which searches produced which facts.
"""
from __future__ import annotations

import logging
import re
import threading
import traceback
from datetime import datetime
from typing import Any

from .. import db, llm
from ..serp import capabilities as cap
from ..services import memory
from ..services.user_settings import get_settings, local_now
from . import decision as dec
from . import errands, explain, intent, research as rs, synthesis, trip as tripmod
from .evidence import fuse, same_product, summarize

log = logging.getLogger("decisionos.orchestrator")

DEFAULT_ORIGIN = (13.0827, 80.2707, "Chennai (default — set your location in Settings)")

# Research needs per decision type -> capability calls (doc §12 "Research Plan").
RESEARCH_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "commerce": [("current_products_prices_reviews", "research_product"), ("expert_and_user_opinion", "search_web")],
    "image": [("identify_product", "analyze_image"), ("current_prices", "research_product")],
    "local": [("nearby_places_ratings_hours", "find_local_places")],
    "errands": [("places_per_stop", "find_local_places"), ("destination", "find_local_places")],
    "travel": [("flights", "research_travel"), ("ground_options", "research_travel")],
    "knowledge": [("papers_patents_news", "research_academic"), ("web_landscape", "search_web")],
    "video": [("candidate_videos", "research_video")],
    "general": [],                      # planned per query by engine/research.py
    "trip": [],                         # planned by engine/trip.py
}

NEED_TEXT = {
    "current_products_prices_reviews": "Find products with prices, ratings and sellers (Google Shopping + Amazon)",
    "expert_and_user_opinion": "Check reviews and user opinions (web + forums)",
    "identify_product": "Identify the item in your photo (Google Lens)",
    "current_prices": "Compare prices for the identified item",
    "nearby_places_ratings_hours": "Find nearby places with ratings, reviews and hours (Google Maps)",
    "places_per_stop": "Find a place for each stop (Google Maps)",
    "destination": "Locate your final destination",
    "flights": "Search flights and fares (Google Flights)",
    "ground_options": "Estimate train / bus options",
    "papers_patents_news": "Search papers, patents and news (Scholar, Patents, News)",
    "web_landscape": "Map the wider landscape (web)",
    "candidate_videos": "Find videos (YouTube)",
}


def _typed_plan(dtype: str, spec: dict) -> dict:
    tasks = [{"id": f"t{i + 1}", "tool": capname, "args": {}, "purpose": NEED_TEXT.get(need, need.replace("_", " ")),
              "status": "planned"} for i, (need, capname) in enumerate(RESEARCH_TEMPLATES[dtype])]
    if dtype == "errands":
        tasks = [{"id": f"t{i + 1}", "tool": "find_local_places", "args": {"q": s["query"]},
                  "purpose": f"{s['label']}: find the best nearby place", "status": "planned"}
                 for i, s in enumerate(spec.get("subtasks") or [])] + tasks[1:]
    assumptions = list(spec.get("notes") or [])
    return {"intent": dtype, "planned_by": "router", "tasks": tasks, "assumptions": assumptions,
            "summary": f"{spec['goal'][:140]}", "missing_info": [],
            "clarifying_question": spec.get("clarifying_question")}


# ------------------------------------------------------------------ persistence helpers
def get_decision(decision_id: str) -> dict | None:
    return db.fetch_one("SELECT * FROM decisions WHERE id=?", (decision_id,))


def _save(decision_id: str, **fields: Any) -> None:
    fields["updated_at"] = db.now_iso()
    db.update("decisions", decision_id, fields)


def _step(research: dict, decision_id: str, stage: str, detail: str, status: str = "done") -> None:
    research.setdefault("steps", []).append({"stage": stage, "detail": detail, "status": status,
                                             "at": db.now_iso()})
    _save(decision_id, research=research)


def _origin(s: dict) -> tuple[float, float, str, bool]:
    home = s.get("home") or {}
    if home.get("lat") is not None and home.get("lng") is not None:
        return float(home["lat"]), float(home["lng"]), home.get("label") or "home", True
    return DEFAULT_ORIGIN[0], DEFAULT_ORIGIN[1], DEFAULT_ORIGIN[2], False


# ------------------------------------------------------------------ public API
def create_decision(query: str, image_url: str | None = None, background: bool = True) -> dict:
    row = {"id": db.new_id("dec"), "query": query.strip(), "decision_type": None, "status": "researching",
           "spec": {}, "result": {}, "candidates": [], "research": {"steps": [], "plan": [], "calls": []},
           "plan": None, "created_at": db.now_iso(), "updated_at": db.now_iso()}
    if image_url:
        row["spec"] = {"image_url": image_url}
    db.insert("decisions", row)
    if background:
        threading.Thread(target=run_decision, args=(row["id"],), daemon=True).start()
    else:
        run_decision(row["id"])
    return get_decision(row["id"])  # type: ignore[return-value]


def run_decision(decision_id: str) -> None:
    d = get_decision(decision_id)
    if not d:
        return
    research = d["research"] or {"steps": []}
    try:
        _run(d, research)
    except Exception as exc:
        log.error("decision %s failed: %s\n%s", decision_id, exc, traceback.format_exc())
        _step(research, decision_id, "error", str(exc)[:300], status="failed")
        _save(decision_id, status="failed", error=str(exc)[:500])


def _run(d: dict, research: dict) -> None:
    did = d["id"]
    now = local_now()
    s = get_settings()
    lat, lng, origin_label, origin_known = _origin(s)
    context = {"location_label": origin_label, "location": {"lat": lat, "lng": lng, "label": origin_label},
               "memories": memory.active_preferences(), "image_url": (d.get("spec") or {}).get("image_url")}

    # 1. UNDERSTAND
    spec = intent.build_spec(d["query"], now, context)
    _save(did, spec=spec, decision_type=spec["decision_type"])
    _step(research, did, "understand",
          f"{spec['decision_type']} decision · {len(spec['criteria'])} criteria · extracted by {spec['extracted_by']}")

    # 2. PLAN — decide (and show) exactly what will be done for this query
    dtype = spec["decision_type"]
    research["plan"] = [{"need": need, "capability": capname} for need, capname in RESEARCH_TEMPLATES[dtype]]
    if dtype == "general":
        task_plan = rs.make_plan(d["query"], spec, context, now)
    elif dtype == "trip":
        task_plan = tripmod.make_plan(spec["trip"], now)
    else:
        task_plan = _typed_plan(dtype, spec)
    research["task_plan"] = task_plan
    if task_plan.get("clarifying_question") and not spec.get("clarifying_question"):
        spec["clarifying_question"] = task_plan["clarifying_question"]
        _save(did, spec=spec)
    _step(research, did, "plan_research", f"{len(task_plan['tasks'])} tasks planned by {task_plan['planned_by']}: "
                                          + "; ".join(t["purpose"] for t in task_plan["tasks"]))

    if dtype == "general":
        _run_research(d, spec, context, research, task_plan)
        return
    if dtype == "trip":
        res = tripmod.run(spec["trip"], task_plan, context, now, lambda stage, detail: _step(research, did, stage, detail))
        research["calls"] = res.pop("calls")
        _save(did, result=res, candidates=[], status="ready", research=research)
        return

    # 3-7. SEARCH -> EVIDENCE -> DECIDE -> EXPLAIN (per type)
    if dtype == "errands":
        if not origin_known:
            spec.setdefault("notes", []).append("Home location not set; routing from a default location.")
        res = errands.plan_errands(spec, (lat, lng), origin_label, s["transport"], now, s.get("places") or {})
        research["calls"] = res.pop("calls")
        cands = res.pop("candidates")
        for t in research["task_plan"]["tasks"]:
            t["status"] = "done"
        _step(research, did, "search", f"{len(research['calls'])} searches across {len(spec['subtasks'])} stops")
        if not origin_known:
            res["warnings"].insert(0, "Set your home/hostel location in Settings for accurate distances.")
        res["stats"] = {"candidates": len(cands), "sources": 1, "searches": len(research["calls"]),
                        "reviews": sum((c["facts"].get("rating") or {}).get("reviews", 0) for c in cands),
                        "failed_searches": sum(1 for c in research["calls"] if not c.get("ok"))}
        res["explanation"] = _errands_explanation(spec, res)
        _step(research, did, "decide", f"{res['totals']['locations']} stops chosen, route optimised")
        _save(did, result=res, candidates=cands, status="ready", research=research)
        return

    observations, calls, demo, extra = _search(dtype, spec, (lat, lng), research, did)
    research["calls"] = calls
    for t in research["task_plan"]["tasks"]:
        t["status"] = "done" if observations else "empty"
    _step(research, did, "search", f"{len(calls)} searches · {len(observations)} results"
                                   + (" · DEMO DATA" if demo else ""))

    kind = {"commerce": "product", "image": "product", "local": "place", "travel": "flight",
            "video": "video", "knowledge": "paper", "general": "article"}[dtype]
    origin = (lat, lng) if dtype == "local" else None
    context_snips = [f"{o['name']}: {o.get('snippet') or ''}" for o in observations if o["kind"] == "article"][:15]

    if dtype == "knowledge":
        cands, landscape, method = synthesis.research_directions(spec["goal"], observations)
        extra["landscape"] = landscape
        if not cands:                                   # fallback: rank sources themselves
            cands = fuse([o for o in observations if o["kind"] in ("paper", "article")])
            spec["criteria"] = [{"key": "attr:cited_by", "label": "Citations", "weight": 0.6, "direction": "max"},
                                {"key": "relevance", "label": "Relevance", "weight": 0.4, "direction": "max"}]
            _save(did, spec=spec)
        _step(research, did, "evidence", f"{len(cands)} candidate directions ({method})")
    else:
        cands = fuse([o for o in observations if o["kind"] == kind], currency=s.get("currency") or "INR", origin=origin)
        if dtype == "image" and extra.get("identified_as"):
            same = [c for c in cands if same_product(c["name"], extra["identified_as"])]
            if same:                       # keep only listings of the identified product
                cands = same
        _step(research, did, "evidence", f"{len(cands)} unique options after de-duplication · "
                                         f"{sum(1 for c in cands if len(c['sources']) > 1)} cross-verified")
        if any(c["key"].startswith("j:") for c in spec["criteria"]):
            pre = dec.decide(cands, {**spec, "criteria": [c for c in spec["criteria"] if not c["key"].startswith("j:")]
                                     or [{"key": "relevance", "label": "Relevance", "weight": 1, "direction": "max"}]},
                             now, explore=False)
            order = {r["id"]: i for i, r in enumerate(pre["ranking"])}
            cands.sort(key=lambda c: order.get(c["id"], 999))
            method = explain.judge(cands, spec, context_snips)
            _step(research, did, "judge", f"Soft criteria scored by {method}")

    result = dec.decide(cands, spec, now)
    stats = summarize(cands, calls)
    result["stats"] = stats
    result["demo"] = demo
    result.update(extra)
    if dtype == "video" and result["winner"]:
        by_id = {c["id"]: c for c in cands}
        ranked = [by_id[r["id"]] for r in result["ranking"]]
        result["learning_path"] = synthesis.learning_path(spec["search_query"], ranked)["items"]
    _step(research, did, "decide", f"{len(result['ranking'])} ranked · {len(result['eliminated'])} eliminated")
    result["explanation"] = explain.explain(spec, result, cands, stats)
    _step(research, did, "explain", f"Explanation by {result['explanation'].get('generated_by')}")
    _save(did, result=result, candidates=cands, status="ready", research=research)


def _run_research(d: dict, spec: dict, context: dict, research: dict, plan: dict) -> None:
    """Open-ended questions: run the planned tools, number the evidence, answer from it."""
    did = d["id"]
    observations, calls, demo = rs.execute(plan, context, d["query"])
    research["calls"] = calls
    fb = [t for t in plan["tasks"] if t.get("fallback")]
    _step(research, did, "search", f"{len(calls)} searches · {len(observations)} results"
                                   + (f" · {len(fb)} fallback(s) used" if fb else "") + (" · DEMO DATA" if demo else ""))
    sections, evidence = rs.build_sections(plan, observations)
    _step(research, did, "evidence", f"{len(evidence)} pieces of evidence across {len(sections)} sources")
    ans = rs.answer(d["query"], plan, evidence)
    _step(research, did, "explain", f"Answer written by {ans['generated_by']}")
    result = {"answer": ans, "sections": sections, "demo": demo, "winner": None, "ranking": [], "eliminated": [],
              "stats": {"candidates": len(evidence), "searches": len(calls), "sources": len({e["source"] for e in evidence}),
                        "failed_searches": sum(1 for c in calls if not c.get("ok")), "reviews": 0},
              "explanation": {"headline": plan.get("summary") or "Here's what I found", "summary": ans["text"],
                              "why": [], "tradeoffs": [], "next_step": "", "generated_by": ans["generated_by"]}}
    _save(did, result=result, candidates=[], status="ready", research=research)


def _search(dtype: str, spec: dict, origin: tuple[float, float], research: dict, did: str):
    q, budget = spec["search_query"], spec["hard_constraints"].get("budget_max")
    extra: dict[str, Any] = {}
    results: list[dict] = []
    if dtype == "commerce":
        results = [cap.research_product(q, budget), cap.search_web(f"{q} review", forums=True)]
    elif dtype == "image":
        lens = cap.analyze_image(spec.get("image_url") or "")
        ident = lens.get("identified_as") or q
        extra["identified_as"] = ident
        _step(research, did, "identify", f"Image identified as: {ident}")
        spec["search_query"] = ident
        _save(did, spec=spec)
        results = [lens, cap.research_product(ident, budget)]
    elif dtype == "local":
        results = [cap.find_local_places(q, origin[0], origin[1])]
    elif dtype == "travel":
        tr = spec.get("travel") or {}
        travel = cap.research_travel(tr.get("origin_city") or "", tr.get("dest_city") or "", tr.get("date"),
                                     tr.get("origin_airport"), tr.get("dest_airport"))
        results = [travel]
        ground, method = synthesis.ground_options(travel.get("route") or {}, travel["observations"])
        travel["observations"] += ground
        if method == "unavailable":
            extra["notes"] = ["No train/bus fares found for this route; showing flights only."]
        elif method == "google_ai_mode":
            extra["notes"] = ["Train/bus fares come from Google AI Mode (typical ranges, not live availability)."]
    elif dtype == "knowledge":
        results = [cap.research_academic(q), cap.search_web(q, forums=False)]
    elif dtype == "video":
        results = [cap.research_video(q)]
    else:
        results = [cap.search_web(q), cap.research_news(q)]
    observations = [o for r in results for o in r["observations"]]
    calls = [c for r in results for c in r["calls"]]
    demo = any(r.get("demo") for r in results)
    return observations, calls, demo, extra


def _errands_explanation(spec: dict, res: dict) -> dict:
    t = res["totals"]
    within = res.get("within_budget")
    budget_txt = "" if within is None else (" ✓ within budget." if within else " ✗ over budget.")
    return {"headline": f"{t['locations']} stops, ~₹{t['cost']:,.0f} total{budget_txt}",
            "summary": f"Route covers {t['distance_km']} km ({t['walking_km']} km walking) in about "
                       f"{t['duration_min']} min. Each stop was picked by rating, distance and review volume.",
            "why": [f"{s['subtask']}: {s['place']['name']} ({s['place'].get('rating') or '–'}★, "
                    f"{(s['place'].get('distance_km') or 0):.1f} km)" for s in res["stops"]],
            "tradeoffs": [], "next_step": "Add the whole plan to your calendar.", "generated_by": "engine"}


# ------------------------------------------------------------------ What if?
WHATIF_SYSTEM = """Convert a "what if" question about a decision into a patch for DecisionOS.
Current spec criteria and constraints are provided. Return JSON:
{"label": "short label for this scenario", "hard_constraints": {only changed keys: budget_max, deadline (ISO), min_rating,
max_distance_km, open_now, must_include}, "weights": {criterion_key: new relative weight}, "add_criteria":
[{"key", "label", "weight", "direction"}], "needs_new_search": bool}"""


def _whatif_fallback(text: str, spec: dict, now: datetime) -> dict:
    patch: dict[str, Any] = {"label": text.strip().rstrip("?")}
    t = text.lower()
    b = intent._budget(t) or (lambda m: float(m.group(1)) * (1000 if m.group(2) else 1) if m else None)(
        re.search(r"(\d+(?:\.\d+)?)\s*(k)?\b", t))
    if b and re.search(r"budget|₹|rs\b|\d+\s*k\b|\d{4,}", t) and "rated" not in t:
        patch["hard_constraints"] = {"budget_max": b}
    if re.search(r"\btoday|tomorrow|tonight|by \w+day\b", t):
        from .timeparse import parse_when
        w = parse_when(t, now)
        if w:
            patch.setdefault("hard_constraints", {})["deadline"] = w.isoformat()
    m = re.search(r"rated\s*(?:above|over|at least)?\s*(\d(?:\.\d)?)", t)
    if m:
        patch.setdefault("hard_constraints", {})["min_rating"] = float(m.group(1))
    m = re.search(r"within\s*(\d+(?:\.\d+)?)\s*km", t)
    if m:
        patch.setdefault("hard_constraints", {})["max_distance_km"] = float(m.group(1))
    for c in spec["criteria"]:
        words = [w for w in re.findall(r"[a-z]+", c["label"].lower()) if len(w) > 3]
        if any(w in t for w in words) and re.search(r"more important|matters? more|prioriti[sz]e|care more", t):
            patch["boost"] = c["key"]
    return patch


def what_if(decision_id: str, text: str | None = None, patch: dict | None = None) -> dict:
    d = get_decision(decision_id)
    if not d or d["status"] not in ("ready", "accepted", "planned"):
        raise ValueError("Decision is not ready yet")
    now = local_now()
    spec = d["spec"]
    if patch is None:
        out = llm.complete_json(WHATIF_SYSTEM, f"Now: {now.isoformat()}\nSpec criteria: {spec['criteria']}\n"
                                               f"Constraints: {spec['hard_constraints']}\nQuestion: {text}", max_tokens=500)
        patch = out if isinstance(out, dict) else _whatif_fallback(text or "", spec, now)
    label = patch.get("label") or text or "Scenario"
    new_spec = dec.apply_patch(spec, patch)
    if d["decision_type"] == "errands":
        s = get_settings()
        lat, lng, label_o, _ = _origin(s)
        res = errands.plan_errands(new_spec, (lat, lng), label_o, s["transport"], now, s.get("places") or {})
        scenario = {"label": label, "patch": patch, "winner": None,
                    "winner_name": f"{len(res['stops'])}/{len(new_spec.get('subtasks') or [])} stops · "
                                   f"~₹{res['totals']['cost']:,.0f} · {res['totals']['duration_min']} min",
                    "result": {k: res[k] for k in ("stops", "totals", "timeline", "warnings", "within_budget")}}
    else:
        cands = d["candidates"]
        if any(c["key"].startswith("j:") and not all(c["key"][2:] in (x.get("judgements") or {}) for x in cands)
               for c in new_spec["criteria"]):
            explain.judge(cands, new_spec, [])
        r = dec.decide(cands, new_spec, now, explore=False)
        by_id = {c["id"]: c for c in cands}
        scenario = {"label": label, "patch": patch, "winner": r["winner"],
                    "winner_name": by_id[r["winner"]]["name"] if r["winner"] else "No option qualifies",
                    "score": r["ranking"][0]["score"] if r["ranking"] else None,
                    "changed": r["winner"] != d["result"].get("winner"),
                    "eliminated_summary": r["eliminated_summary"], "criteria": new_spec["criteria"],
                    "hard_constraints": new_spec["hard_constraints"],
                    "ranking": r["ranking"][:5]}
        if patch.get("needs_new_search"):
            scenario["note"] = "This scenario may need fresh searches — use 'Adopt & re-research' for full accuracy."
    result = d["result"]
    result.setdefault("scenarios", []).append({**scenario, "at": db.now_iso()})
    _save(decision_id, result=result)
    return scenario


def adopt_scenario(decision_id: str, index: int) -> dict:
    """Make a what-if scenario the main decision (re-scores; errands re-plans)."""
    d = get_decision(decision_id)
    sc = d["result"]["scenarios"][index]
    now = local_now()
    new_spec = dec.apply_patch(d["spec"], sc["patch"])
    if d["decision_type"] == "errands":
        s = get_settings()
        lat, lng, label_o, _ = _origin(s)
        res = errands.plan_errands(new_spec, (lat, lng), label_o, s["transport"], now, s.get("places") or {})
        res.pop("calls")
        cands = res.pop("candidates")
        res["stats"] = d["result"].get("stats")
        res["explanation"] = _errands_explanation(new_spec, res)
        res["scenarios"] = d["result"].get("scenarios", [])
        _save(decision_id, spec=new_spec, result=res, candidates=cands, plan=None, status="ready")
        return get_decision(decision_id)
    cands = d["candidates"]
    r = dec.decide(cands, new_spec, now)
    r["stats"] = d["result"].get("stats")
    for k in ("demo", "learning_path", "landscape", "identified_as", "answer", "scenarios"):
        if k in d["result"]:
            r[k] = d["result"][k]
    r["explanation"] = explain.explain(new_spec, r, cands, r["stats"] or {})
    _save(decision_id, spec=new_spec, result=r, plan=None, status="ready")
    return get_decision(decision_id)


def choose_option(decision_id: str, candidate_id: str) -> dict:
    """User overrides the recommendation (user stays in control) — re-explain around their pick."""
    d = get_decision(decision_id)
    result = d["result"]
    result["user_choice"] = candidate_id
    _save(decision_id, result=result)
    return get_decision(decision_id)


def accept_decision(decision_id: str) -> dict:
    """User accepts the recommendation (or their own pick): store the decision in memory and
    record behavioural signals (which may lead to a *proposed* preference, never a silent one)."""
    d = get_decision(decision_id)
    if not d:
        raise KeyError(decision_id)
    res = d["result"] or {}
    chosen_id = res.get("user_choice") or res.get("winner")
    by_id = {c["id"]: c for c in d.get("candidates") or []}
    chosen = by_id.get(chosen_id)
    _save(decision_id, status="accepted")
    reason = ", ".join((res.get("explanation") or {}).get("why", [])[:2])
    label = chosen["name"] if chosen else (res.get("explanation") or {}).get("headline", d["query"])
    memory.add_memory(f"Decided: {label} — for “{d['query'][:80]}”" + (f" (reason: {reason})" if reason else ""),
                      kind="decision", source="system", meta={"decision_id": decision_id})
    proposed = []
    signals = []
    if d["decision_type"] in ("commerce", "image"):
        signals.append("chose_online")
    if d["decision_type"] == "errands" and any(s["subtask"].lower().startswith("buy") for s in res.get("stops", [])):
        signals.append("chose_local")
    alts = {a["label"]: a["id"] for a in res.get("alternatives", [])}
    if chosen and chosen_id:
        prices = [metric for metric in (dec.metric(c, "price") for c in by_id.values()) if metric is not None]
        cp = dec.metric(chosen, "price")
        if cp is not None and prices and cp <= min(prices) * 1.02:
            signals.append("chose_cheapest")
        if alts.get("Highest rated") == chosen_id:
            signals.append("chose_top_rated")
        if d["decision_type"] == "local":
            dists = [dec.metric(c, "distance") for c in by_id.values() if dec.metric(c, "distance") is not None]
            if dists and dec.metric(chosen, "distance") == min(dists):
                signals.append("chose_closest")
    for sig in signals:
        p = memory.record_signal(sig, decision_id)
        if p:
            proposed.append(p)
    if proposed:
        from ..services import interventions
        for p in proposed:
            interventions.create("MEMORY_CONFIRMATION", "Should I remember this?",
                                 f"You seem to: {p['content'].lower()}. Should I remember this for future decisions?",
                                 0.5, 0.8, 0.7,
                                 [{"type": "confirm_memory", "label": "Yes, remember", "memory_id": p["id"]},
                                  {"type": "reject_memory", "label": "No", "memory_id": p["id"]}], force=True)
    return get_decision(decision_id)
