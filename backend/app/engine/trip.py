"""Trip planner: "suggest a 3-day trip within 600 km of Chennai under ₹8,000".

Two dependent stages (the second needs the first's output):
  1. DISCOVER candidate destinations (web + forum search), unless the user named one.
  2. For each candidate, in parallel: STAYS for the trip dates (Google Hotels) and THINGS TO DO (Tripadvisor).
Then: distance (from hotel coordinates), a cost model per destination (every number labelled as observed or
estimated), hard-constraint filtering (budget, distance), ranking, and a day-by-day itinerary for the winner.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any

from .. import llm
from ..serp import capabilities as cap, registry
from .evidence import haversine_km
from .intent import AIRPORTS
from .research import _TASK_POOL, evidence_status

MAX_CANDIDATES = 4
NOT_DESTINATION = (r"\b(budget|tips?|day \d|itinerary|costs?|how|best time|travel|transport|booking|operators?|highlights?|"
                   r"getting there|accommodation|stay|food|weather|season|packing|summary|note|why|what|tours?)\b")
ROAD_FACTOR = 1.25                 # straight-line -> road distance
FARE_PER_KM = 1.6                  # typical bus/train fare per person per km (estimate)
FOOD_PER_DAY = 500                 # per person (estimate)
LOCAL_PER_DAY = 400                # local transport + entry tickets per person (estimate)
AVG_SPEED_KMH = 50

NOT_PLACES = {
    "best", "top", "day", "days", "trip", "trips", "places", "place", "visit", "here", "list", "the", "hill", "hills",
    "station", "stations", "india", "indian", "tamil", "nadu", "karnataka", "kerala", "andhra", "pradesh", "telangana",
    "tour", "tours", "packages", "package", "weekend", "getaway", "getaways", "near", "from", "within", "km", "kms",
    "things", "to", "do", "travel", "guide", "budget", "family", "friends", "beach", "beaches", "temple", "temples",
    "city", "cities", "south", "north", "east", "west", "tripadvisor", "reddit", "holiday", "holidays", "spots",
    "destinations", "destination", "road", "routes", "nature", "wildlife", "tourist", "attractions", "morning",
    "evening", "afternoon", "how", "what", "where", "why", "when", "which", "you", "your", "this", "these", "those",
    "with", "and", "for", "in", "of", "on", "at", "a", "an", "is", "are", "most", "popular", "famous", "short",
    "long", "amazing", "beautiful", "wonderful", "perfect", "great", "explore", "hidden", "gems", "nights", "night",
    "stay", "hotels", "hotel", "resorts", "plan", "itinerary", "complete", "ultimate", "people", "kapaleeshwarar",
}
ALIASES = {"puducherry": "Pondicherry", "pondy": "Pondicherry", "ooty": "Ooty", "udhagamandalam": "Ooty",
           "bengaluru": "Bangalore", "mysuru": "Mysore", "kodai": "Kodaikanal", "mahabs": "Mahabalipuram",
           "mamallapuram": "Mahabalipuram"}


# ------------------------------------------------------------------ dates & plan
def trip_dates(trip: dict, now: datetime) -> tuple[str, str, bool]:
    """(check_in, check_out, assumed?) — defaults to the coming Friday when no date was given."""
    days = max(1, int(trip.get("days") or 2))
    if trip.get("start_date"):
        try:
            start = date.fromisoformat(str(trip["start_date"])[:10])
            return start.isoformat(), (start + timedelta(days=max(1, days - 1))).isoformat(), False
        except ValueError:
            pass
    start = now.date() + timedelta(days=(4 - now.weekday()) % 7 or 7)   # next Friday
    return start.isoformat(), (start + timedelta(days=max(1, days - 1))).isoformat(), True


def make_plan(trip: dict, now: datetime) -> dict[str, Any]:
    ci, co, assumed = trip_dates(trip, now)
    origin, dest = trip.get("origin") or "your location", trip.get("destination")
    tasks = []
    if not dest:
        # this phrasing reliably gets Google's AI Overview list of destinations with distances
        q = f"weekend getaways near {origin}" if (trip.get("days") or 2) <= 3 else f"best {trip['days']} day trips from {origin}"
        tasks += [{"id": "t1", "tool": "web_search", "args": {"q": q}, "purpose": "Find candidate destinations",
                   "status": "planned", "stage": 1},
                  {"id": "t2", "tool": "forum_search", "args": {"q": f"best {trip.get('days') or 2} day trip from {origin}"},
                   "purpose": "What travellers recommend", "status": "planned", "stage": 1}]
        airport = AIRPORTS.get((trip.get("origin") or "").lower())
        if airport and (not trip.get("max_km") or trip["max_km"] >= 800):
            tasks.append({"id": "t0", "tool": "explore_destinations",
                          "args": {"from_airport": airport, "outbound_date": ci, "weekend": str((trip.get("days") or 2) <= 3).lower()},
                          "purpose": f"Destinations you can fly to from {airport}, with flight prices", "status": "planned", "stage": 1})
    target = dest or f"top {MAX_CANDIDATES} destinations"
    tasks += [{"id": "t3", "tool": "stays", "args": {"q": target, "check_in": ci, "check_out": co},
               "purpose": f"Stay prices for {ci} → {co} in {target}", "status": "planned", "stage": 2},
              {"id": "t4", "tool": "tripadvisor", "args": {"q": target, "category": "things_to_do"},
               "purpose": f"Things to do in {target}", "status": "planned", "stage": 2},
              {"id": "t6", "tool": "directions", "args": {"from": origin, "to": target, "mode": "driving"},
               "purpose": f"Road distance and drive time to {target}", "status": "planned", "stage": 2}]
    assumptions = [f"Dates not given — planned for {ci} → {co}."] if assumed else []
    assumptions.append(f"Travel cost: bus/train fares from Google AI Mode for the chosen place, ₹{FARE_PER_KM}/km estimate "
                       f"for the others; food ₹{FOOD_PER_DAY} and local travel ₹{LOCAL_PER_DAY} per person per day.")
    return {"intent": "trip_planning", "planned_by": "trip planner",
            "summary": (f"Plan a {trip.get('days') or 2}-day trip from {origin}"
                        + (f" to {dest}" if dest else f", comparing up to {MAX_CANDIDATES} destinations")
                        + (f" within {trip['max_km']:g} km" if trip.get("max_km") else "")
                        + (f" under ₹{trip['budget']:,.0f}" if trip.get("budget") else "") + "."),
            "tasks": tasks, "assumptions": assumptions, "missing_info": ["travel dates"] if assumed else [],
            "clarifying_question": "Which dates are you travelling, and how many people?" if assumed else None}


# ------------------------------------------------------------------ destination discovery
DEST_SYSTEM = """Extract candidate trip destinations from web snippets for DecisionOS.
Only include real towns/regions that the snippets mention as places to visit (not the origin city, not hotels).
For each give the road distance from the origin from general knowledge, marked as an estimate.
Return JSON: {"destinations": [{"name": str, "state": str, "approx_road_km": number, "why": "short reason"}]} (max 8)."""


def discover(trip: dict, observations: list[dict]) -> tuple[list[dict], str]:
    origin = (trip.get("origin") or "").lower()
    snips = [{"title": o["name"], "snippet": (o.get("snippet") or "")[:300]} for o in observations[:20]]
    out = llm.complete_json(DEST_SYSTEM, json.dumps({"origin": trip.get("origin"), "days": trip.get("days"),
                                                     "max_km": trip.get("max_km"), "snippets": snips}), max_tokens=1200)
    if isinstance(out, dict) and isinstance(out.get("destinations"), list):
        found = [{"name": d["name"], "approx_km": _f(d.get("approx_road_km")), "why": d.get("why")}
                 for d in out["destinations"] if isinstance(d, dict) and d.get("name")
                 and d["name"].lower() != origin]
        if found:
            return found, "claude"
    # Google's AI Overview usually lists destinations as clean list items — use those first.
    listed, seen = [], set()
    for o in observations:
        if (o.get("attrs") or {}).get("overview_item"):
            name = re.split(r"\s*(?:[(,:–]|\s-\s|\s&\s|\sand\s)", o["name"])[0].strip()
            name = ALIASES.get(name.lower(), name)
            text = o.get("snippet") or ""
            kms = re.search(r"(\d{2,4})(?:\s*[–-]\s*(\d{2,4}))?\s*km", text)
            if 2 < len(name) < 40 and name.lower() != origin and name.lower() not in seen \
                    and not re.search(NOT_DESTINATION, name.lower()):
                seen.add(name.lower())
                listed.append({"name": name, "approx_km": float(kms.group(2) or kms.group(1)) if kms else None,
                               "why": text[:160] or "listed by Google"})
    if len(listed) >= 2:
        return listed[:12], "google ai overview"
    counts: Counter = Counter()
    for o in observations:
        seen_here = set()
        for chunk in re.split(r"[·|•;:\n]|\s\d{1,2}\.\s|,\s|\s-\s|\s–\s|\(|\)", f"{o.get('name') or ''} · {o.get('snippet') or ''}"):
            words = re.findall(r"[A-Z][a-z]{2,}", chunk.strip())[:2]
            words = [w for w in words if w.lower() not in NOT_PLACES]
            if not words:
                continue
            name = ALIASES.get(words[0].lower(), words[0])
            if name.lower() != origin and name not in seen_here:
                seen_here.add(name)
                counts[name] += 1
    return [{"name": n, "approx_km": None, "why": f"mentioned in {c} sources"} for n, c in counts.most_common(8)
            if c >= 2 or len(counts) < 4], "heuristic"


# ------------------------------------------------------------------ per-destination research
def research_destination(name: str, ci: str, co: str, adults: int, context: dict, origin: str | None) -> dict:
    # Google Hotels only (no Airbnb) for the comparison: dated prices at half the search cost
    stays = cap.research_hotels_and_rentals(name, ci, co, adults, rentals=False)
    todo = registry.run_tool("tripadvisor", {"q": name, "category": "things_to_do"}, context)
    route = (registry.run_tool("directions", {"from": origin, "to": name, "mode": "driving"}, context)
             if origin else {"observations": [], "calls": []})
    return {"stays": stays, "todo": todo, "route": route}


def _f(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def cost_option(name: str, trip: dict, origin_ll: tuple[float, float] | None, approx_km: float | None,
                stays: list[dict], todo: list[dict], ci: str, co: str, route: list[dict] | None = None) -> dict[str, Any]:
    days = max(1, int(trip.get("days") or 2))
    nights = max(1, days - 1)
    people = max(1, int(trip.get("travellers") or 1))
    gps = [(o["lat"], o["lng"]) for o in stays if o.get("lat") is not None]
    road = next((r for r in route or [] if (r.get("attrs") or {}).get("distance_km")), None)
    drive_hours = None
    if road:                                               # real road distance from Google Maps Directions
        km, km_basis = round(road["attrs"]["distance_km"]), "Google Maps driving route"
        drive_hours = round(road["attrs"]["duration_min"] / 60, 1) if road["attrs"].get("duration_min") else None
    elif origin_ll and gps:
        lat, lng = median(g[0] for g in gps), median(g[1] for g in gps)
        km, km_basis = round(haversine_km(origin_ll[0], origin_ll[1], lat, lng) * ROAD_FACTOR), "estimated from hotel locations"
    elif approx_km:
        km, km_basis = round(approx_km), "approximate (general knowledge)"
    else:
        km, km_basis = None, "unknown"
    priced = sorted((o for o in stays if o.get("price")), key=lambda o: o["price"])
    # prefer a decently rated cheap stay over the absolute cheapest
    good = [o for o in priced if (o.get("rating") or 0) >= 3.8] or priced
    stay = good[0] if good else None
    rooms = max(1, -(-people // 2))
    costs = {
        "transport": round(km * 2 * FARE_PER_KM * people) if km else None,
        "stay": round(stay["price"] * nights * rooms) if stay else None,
        "food": FOOD_PER_DAY * days * people,
        "local": LOCAL_PER_DAY * days * people,
    }
    total = sum(v for v in costs.values() if v is not None)
    missing = [k for k, v in costs.items() if v is None]
    budget, max_km = trip.get("budget"), trip.get("max_km")
    attractions = [{"name": o["name"], "url": o.get("url"), "snippet": (o.get("snippet") or "")[:200]}
                   for o in sorted(todo, key=lambda o: o.get("position") or 99) if o.get("name")][:8]
    reasons = []
    if budget and total > budget:
        reasons.append(f"Estimated ₹{total:,.0f} is over your ₹{budget:,.0f} budget")
    if max_km and km and km > max_km * 1.1:
        reasons.append(f"About {km} km away (limit {max_km:g} km)")
    if trip.get("min_km") and km and km < trip["min_km"] * 0.9:
        reasons.append(f"Only about {km} km away (you wanted at least {trip['min_km']:g} km)")
    return {"name": name, "distance_km": km, "distance_basis": km_basis,
            "travel_hours": drive_hours or (round(km / AVG_SPEED_KMH, 1) if km else None),
            "costs": costs, "total": total, "missing_costs": missing,
            "within_budget": (total <= budget) if budget else None,
            "eliminated": reasons,
            "stay": ({"name": stay["name"], "price_per_night": stay["price"], "rating": stay.get("rating"),
                      "reviews": stay.get("reviews"), "url": stay.get("url"), "source": stay.get("source"),
                      "status": evidence_status(stay), "nights": nights, "rooms": rooms,
                      "property_token": (stay.get("attrs") or {}).get("property_token")} if stay else None),
            "stay_options": len(priced), "attractions": attractions,
            "dates": {"check_in": ci, "check_out": co}}


def rank(options: list[dict], trip: dict) -> list[dict]:
    ok = [o for o in options if not o["eliminated"]]
    if not ok:
        return options
    lo, hi = min(o["total"] for o in ok), max(o["total"] for o in ok)
    for o in ok:
        cheap = 1.0 if hi == lo else 1 - (o["total"] - lo) / (hi - lo)
        things = min(len(o["attractions"]), 8) / 8
        rating = ((o["stay"] or {}).get("rating") or 3.5) / 5
        known = 0 if o["missing_costs"] else 1
        o["score"] = round(100 * (0.4 * cheap + 0.3 * things + 0.15 * rating + 0.15 * known), 1)
    ok.sort(key=lambda o: -o["score"])
    return ok + [o for o in options if o["eliminated"]]


# ------------------------------------------------------------------ itinerary + explanation
ITIN_SYSTEM = """Write a realistic day-by-day itinerary for DecisionOS using ONLY the attractions listed (you may add
generic items like "travel", "check in", "local market walk"). Respect the travel time on day 1 and the last day.
Return JSON: {"days": [{"day": 1, "title": str, "items": [str]}]}"""


def ai_guide(opt: dict, trip: dict, context: dict) -> dict:
    """Google AI Mode: how to get there (with fares) + a day-by-day plan for the chosen destination."""
    days = max(1, int(trip.get("days") or 2))
    q = (f"{days} day itinerary for {opt['name']}" + (f" from {trip['origin']}" if trip.get("origin") else "")
         + " with how to travel and budget")
    res = registry.run_tool("ai_answer", {"q": q}, context)
    text = next((o["snippet"] for o in res["observations"] if (o.get("attrs") or {}).get("ai_answer")), "") or ""
    refs = [{"title": o["name"], "url": o.get("url"), "source": o.get("source")}
            for o in res["observations"] if (o.get("attrs") or {}).get("ai_reference")][:6]
    return {"text": text, "transport": cap.parse_transport_options(text), "days": cap.parse_itinerary(text),
            "sources": refs, "calls": res["calls"], "query": q}


def apply_ai_fares(opt: dict, trip: dict, transport: list[dict]) -> None:
    """Replace the per-km transport estimate with the cheapest bus/train fare Google AI Mode reports."""
    people = max(1, int(trip.get("travellers") or 1))
    shared = [t for t in transport if t.get("cost_low") and not t["per_vehicle"]]
    if not shared:
        return
    best = min(shared, key=lambda t: t["cost_low"])
    one_way = (best["cost_low"] + (best["cost_high"] or best["cost_low"])) / 2
    opt["costs"]["transport"] = round(one_way * 2 * people)
    opt["transport_basis"] = f"{best['label']}: ₹{best['cost_low']:,.0f}–₹{best['cost_high']:,.0f} one way (Google AI Mode)"
    opt["total"] = sum(v for v in opt["costs"].values() if v is not None)
    opt["missing_costs"] = [k for k, v in opt["costs"].items() if v is None]
    if trip.get("budget"):
        opt["within_budget"] = opt["total"] <= trip["budget"]


def itinerary(opt: dict, trip: dict, guide_days: list[dict] | None = None) -> tuple[list[dict], str]:
    days = max(1, int(trip.get("days") or 2))
    out = llm.complete_json(ITIN_SYSTEM, json.dumps({"origin": trip.get("origin"), "destination": opt["name"],
                                                     "days": days, "travel_hours_each_way": opt.get("travel_hours"),
                                                     "stay": (opt.get("stay") or {}).get("name"),
                                                     "attractions": opt["attractions"]}), max_tokens=1200)
    if isinstance(out, dict) and isinstance(out.get("days"), list) and out["days"]:
        return out["days"], "claude"
    if guide_days and len(guide_days) >= max(1, days - 1):
        return guide_days[:days], "google_ai_mode"
    sights = [a["name"] for a in opt["attractions"]] or [f"Explore {opt['name']}"]
    hrs = opt.get("travel_hours")
    plan, i = [], 0
    for d in range(1, days + 1):
        items = []
        if d == 1:
            items.append(f"Travel {trip.get('origin') or 'from home'} → {opt['name']}" + (f" (~{hrs:g} h)" if hrs else ""))
            if opt.get("stay"):
                items.append(f"Check in at {opt['stay']['name']}")
        per_day = 1 if d in (1, days) else 3
        for _ in range(per_day):
            if i < len(sights):
                items.append(sights[i])
                i += 1
        if d == days and days > 1:
            items.append(f"Return to {trip.get('origin') or 'home'}" + (f" (~{hrs:g} h)" if hrs else ""))
        plan.append({"day": d, "title": "Arrive & explore" if d == 1 else "Head home" if d == days else "Explore",
                     "items": items})
    return plan, "template"


def explanation(trip: dict, ranked: list[dict]) -> dict[str, Any]:
    best = ranked[0] if ranked and not ranked[0]["eliminated"] else None
    if not best:
        closest = min(ranked, key=lambda o: o["total"]) if ranked else None
        return {"headline": "No destination fits all your limits.",
                "summary": (f"The cheapest option found was {closest['name']} at about ₹{closest['total']:,.0f}. "
                            "Try a higher budget, fewer days or a shorter distance.") if closest else
                           "I couldn't find candidate destinations for this trip.",
                "why": [], "tradeoffs": [], "next_step": "Adjust budget, days or distance and re-run.",
                "generated_by": "engine"}
    c = best["costs"]
    why = [f"Estimated total ₹{best['total']:,.0f}" + (f" — ₹{trip['budget'] - best['total']:,.0f} under budget"
                                                       if trip.get("budget") else "")]
    if best["distance_km"]:
        why.append(f"About {best['distance_km']} km away (~{best['travel_hours']:g} h drive each way, {best['distance_basis']})")
    if best.get("transport_basis"):
        why.append(f"Getting there: {best['transport_basis']}")
    if best["stay"]:
        s = best["stay"]
        why.append(f"Stay: {s['name']} at ₹{s['price_per_night']:,.0f}/night"
                   + (f", {s['rating']}★" if s.get("rating") else "") + f" ({s['status']})")
    if best["attractions"]:
        why.append(f"{len(best['attractions'])} things to do found, e.g. {', '.join(a['name'] for a in best['attractions'][:3])}")
    if best["missing_costs"]:
        why.append(f"Not priced: {', '.join(best['missing_costs'])} — total may be higher")
    alts = [o for o in ranked[1:3] if not o["eliminated"]]
    return {"headline": f"{best['name']} is the best fit for your trip.",
            "summary": (f"Transport ~₹{c['transport'] or 0:,.0f}, stay ~₹{c['stay'] or 0:,.0f}, food ~₹{c['food']:,.0f}, "
                        f"local ~₹{c['local']:,.0f}. The hotel rate is the lowest listed for your dates"
                        + (" and the fare comes from Google AI Mode" if best.get("transport_basis") else "")
                        + "; food and local costs are estimates. Confirm availability before booking."),
            "why": why, "tradeoffs": [f"{o['name']}: ~₹{o['total']:,.0f}" + (f", {o['distance_km']} km" if o['distance_km'] else "")
                                      for o in alts],
            "next_step": "Check the dates, then book the stay and transport.", "generated_by": "engine"}


# ------------------------------------------------------------------ main entry
def run(trip: dict, plan: dict, context: dict, now: datetime, step) -> dict[str, Any]:
    """`step(stage, detail)` logs progress. Returns the decision result."""
    ci, co, _ = trip_dates(trip, now)
    people = max(1, int(trip.get("travellers") or 1))
    calls: list[dict] = []
    demo = False
    by_id = {t["id"]: t for t in plan["tasks"]}

    # origin coordinates
    origin_ll = None
    loc = context.get("location") or {}
    home_city = re.split(r"[,(]", context.get("location_label") or "")[0].strip().lower()
    if not trip.get("origin") or trip["origin"].lower() in home_city or home_city in trip["origin"].lower():
        if loc.get("lat") is not None:
            origin_ll = (loc["lat"], loc["lng"])
    if origin_ll is None and trip.get("origin"):
        g = registry.run_tool("local_places", {"q": trip["origin"], "near_me": False}, context)
        calls += g["calls"]
        pts = [o for o in g["observations"] if o.get("lat") is not None]
        origin_ll = (pts[0]["lat"], pts[0]["lng"]) if pts else None

    # stage 1: discover
    if trip.get("destination"):
        candidates, method = [{"name": trip["destination"], "approx_km": None, "why": "you chose it"}], "user"
    else:
        stage1 = [t for t in ("t1", "t2", "t0") if t in by_id]
        futs = [_TASK_POOL.submit(registry.run_tool, by_id[t]["tool"], by_id[t]["args"], context) for t in stage1]
        obs = []
        for tid, f in zip(stage1, futs):
            r = f.result()
            obs += r["observations"]
            calls += r["calls"]
            demo = demo or bool(r.get("demo"))
            by_id[tid].update(status="done" if r["observations"] else "empty", count=len(r["observations"]))
        candidates, method = discover(trip, [o for o in obs if o["kind"] != "destination" or o["engine"] != "google_travel_explore"])
        flown = [o for o in obs if o["engine"] == "google_travel_explore" and o.get("name")]
        if flown:                                   # air destinations with real fares join the shortlist
            known = {c["name"].lower() for c in candidates}
            for o in sorted(flown, key=lambda o: o.get("price") or 1e9)[:3]:
                if o["name"].lower() not in known:
                    km = (haversine_km(origin_ll[0], origin_ll[1], o["lat"], o["lng"]) * ROAD_FACTOR
                          if origin_ll and o.get("lat") is not None else None)
                    candidates.append({"name": o["name"], "approx_km": km,
                                       "why": f"flights from ₹{o['price']:,.0f} (Google Travel Explore)" if o.get("price") else "by air"})
        if trip.get("max_km"):   # use known approximate distances to skip obviously-too-far places before paying for searches
            near = [c for c in candidates if not c["approx_km"] or c["approx_km"] <= trip["max_km"] * 1.1]
            candidates = near or candidates
            # a long trip with a large radius: favour places that use it (3 days for a 60 km hop is a waste)
            if (trip.get("days") or 2) >= 3 and trip["max_km"] >= 300:
                candidates.sort(key=lambda c: -(c["approx_km"] or 0) if (c["approx_km"] or 0) >= 100 else 1e9)
        step("discover", f"{len(candidates)} candidate destinations ({method}): "
                         + ", ".join(c["name"] for c in candidates[:MAX_CANDIDATES]))
    candidates = candidates[:MAX_CANDIDATES]

    # stage 2: per destination, in parallel
    futs = {c["name"]: _TASK_POOL.submit(research_destination, c["name"], ci, co, people, context, trip.get("origin"))
            for c in candidates}
    options, n_stays, n_todo = [], 0, 0
    for c in candidates:
        r = futs[c["name"]].result()
        calls += r["stays"]["calls"] + r["todo"]["calls"] + r["route"]["calls"]
        demo = demo or bool(r["stays"].get("demo") or r["todo"].get("demo"))
        stays = [o for o in r["stays"]["observations"] if o["kind"] == "hotel"]
        todo = [o for o in r["todo"]["observations"] if o["kind"] in ("attraction", "destination")]
        n_stays += len(stays)
        n_todo += len(todo)
        options.append(cost_option(c["name"], trip, origin_ll, c.get("approx_km"), stays, todo, ci, co,
                                   r["route"]["observations"]))
    by_id["t3"].update(status="done" if n_stays else "empty", count=n_stays,
                       args={**by_id["t3"]["args"], "q": ", ".join(c["name"] for c in candidates)})
    by_id["t4"].update(status="done" if n_todo else "empty", count=n_todo,
                       args={**by_id["t4"]["args"], "q": ", ".join(c["name"] for c in candidates)})
    n_routes = sum(1 for o in options if o["distance_basis"] == "Google Maps driving route")
    if "t6" in by_id:
        by_id["t6"].update(status="done" if n_routes else "empty", count=n_routes,
                           args={**by_id["t6"]["args"], "to": ", ".join(c["name"] for c in candidates)})
    step("search", f"{len(calls)} searches · {n_stays} stays · {n_todo} things to do")

    ranked = rank(options, trip)
    winner = ranked[0] if ranked and not ranked[0]["eliminated"] else None
    guide = None
    if winner:
        guide = ai_guide(winner, trip, context)
        calls += guide.pop("calls")
        apply_ai_fares(winner, trip, guide["transport"])
        winner["how_to_get_there"] = guide["transport"]
        token = (winner.get("stay") or {}).get("property_token")
        if token:                                  # what guests say about the recommended stay
            hr = registry.run_tool("hotel_reviews", {"property_token": token}, context)
            calls += hr["calls"]
            winner["stay"]["guest_reviews"] = [{"text": o["snippet"], "rating": o.get("rating"),
                                                 "date": (o.get("attrs") or {}).get("date"),
                                                 "subratings": (o.get("attrs") or {}).get("subratings")}
                                                for o in hr["observations"][:3]]
        by_id["t5"] = {"id": "t5", "tool": "ai_answer", "args": {"q": guide["query"]},
                       "purpose": f"How to get to {winner['name']}, fares and a day-by-day plan (Google AI Mode)",
                       "status": "done" if guide["text"] else "empty", "count": len(guide["transport"]) + len(guide["days"])}
        plan["tasks"].append(by_id["t5"])
    days_plan, itin_by = itinerary(winner, trip, (guide or {}).get("days")) if winner else ([], "none")
    step("decide", f"{sum(1 for o in ranked if not o['eliminated'])} of {len(ranked)} destinations fit your limits")
    return {"trip": {**trip, "check_in": ci, "check_out": co}, "options": ranked,
            "winner": winner["name"] if winner else None, "itinerary": days_plan, "itinerary_by": itin_by,
            "guide_sources": (guide or {}).get("sources") or [],
            "explanation": explanation(trip, ranked), "calls": calls, "demo": demo,
            "stats": {"candidates": len(ranked), "searches": len(calls),
                      "failed_searches": sum(1 for c in calls if not c.get("ok")), "sources": 3,
                      "reviews": sum(((o.get("stay") or {}).get("reviews") or 0) for o in ranked)}}
