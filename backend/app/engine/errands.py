"""Errand planner: "buy X, print Y, reach Z by 4 PM with ₹1,000".

For every sub-task it runs a local decision (Maps -> evidence -> score), then orders the stops
to minimise travel, estimates legs (walk vs ride), costs and a timeline that lands before the
deadline. Opening hours are checked against the planned arrival at each stop.
"""
from __future__ import annotations

import itertools
import re
from datetime import datetime, timedelta
from typing import Any

from ..serp import capabilities as cap
from . import decision as dec
from .evidence import fuse, haversine_km

ROAD_FACTOR = 1.3          # straight-line -> street distance
RIDE_WAIT_MIN = 6
BUFFER_MIN = 10
LOCAL_CRITERIA = [
    {"key": "rating", "label": "Rating", "weight": 0.3, "direction": "max"},
    {"key": "distance", "label": "Distance", "weight": 0.4, "direction": "min"},
    {"key": "review_confidence", "label": "Review volume", "weight": 0.2, "direction": "max"},
    {"key": "availability", "label": "Open now", "weight": 0.1, "direction": "max"},
]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _hours_for(hours: Any, day: datetime) -> tuple[int, int] | None:
    """Parse '9 AM–9 PM' style opening hours for that weekday -> (open_min, close_min)."""
    if not isinstance(hours, dict):
        return None
    text = hours.get(DAYS[day.weekday()])
    if not text or "24" in str(text):
        return (0, 24 * 60) if text and "24" in str(text) else None
    if "closed" in str(text).lower():
        return (0, 0)
    times = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)?", str(text).upper())
    if len(times) < 2:
        return None

    def to_min(t: tuple[str, str, str], fallback_pm: bool) -> int:
        h, m, ap = int(t[0]), int(t[1] or 0), t[2] or ("PM" if fallback_pm else "AM")
        h = (0 if h == 12 else h) + (12 if ap == "PM" else 0)
        return h * 60 + m
    return to_min(times[0], False), to_min(times[-1], True)


def _leg(a: tuple[float, float], b: tuple[float, float], transport: dict) -> dict:
    km = haversine_km(a[0], a[1], b[0], b[1]) * ROAD_FACTOR
    if km <= transport["walk_max_km"]:
        return {"mode": "walk", "km": round(km, 2), "minutes": max(2, round(km / transport["walk_kmh"] * 60)), "cost": 0}
    minutes = round(km / transport["ride_kmh"] * 60) + RIDE_WAIT_MIN
    return {"mode": "auto/cab", "km": round(km, 2), "minutes": minutes,
            "cost": max(30, round(km * transport["ride_cost_per_km"]))}


def _stop_cost(c: dict, sub: dict) -> tuple[float, str]:
    rng = cap.parse_price_range((c.get("attrs") or {}).get("price_level"))
    est = sub.get("est_cost")
    if est is not None and rng and rng[0] <= est <= rng[1] * 1.5:
        return float(est), "your estimate within shop's price range"
    if est is not None:
        return float(est), "estimate"
    if rng:
        return round((rng[0] + rng[1]) / 2), "shop price range"
    return 0.0, "unknown"


def _pick_destination(spec: dict, origin: tuple[float, float], saved_places: dict) -> tuple[dict | None, list[dict], list[str]]:
    dest = spec.get("destination") or {}
    label = (dest.get("label") or "").strip()
    warnings: list[str] = []
    if not label:
        return None, [], warnings
    if label.lower() in ("home", "my home", "hostel", "my hostel", "room", "my room", "house"):
        return {"name": label.title(), "lat": origin[0], "lng": origin[1], "address": None, "saved": True}, [], warnings
    for key, place in (saved_places or {}).items():
        if key.lower() in label.lower() or label.lower() in key.lower():
            if place.get("lat") is not None:
                return {"name": place.get("label") or key.title(), "lat": place["lat"], "lng": place["lng"],
                        "address": place.get("address"), "saved": True}, [], warnings
    res = cap.find_local_places(dest.get("query") or label, origin[0], origin[1])
    cands = [c for c in fuse(res["observations"], origin=origin) if c.get("lat") is not None]
    if not cands:
        warnings.append(f"Couldn't locate '{label}'. Save it under Settings → Places for accurate routing.")
        return None, res["calls"], warnings
    best = min(cands, key=lambda c: (c.get("position") or 99))
    warnings.append(f"Assumed '{label}' is {best['name']}. Save your own {label.lower()} under Settings → Places.")
    return {"name": best["name"], "lat": best["lat"], "lng": best["lng"], "address": best.get("address"),
            "saved": False}, res["calls"], warnings


def plan_errands(spec: dict, origin: tuple[float, float], origin_label: str, transport: dict,
                 now: datetime, saved_places: dict | None = None) -> dict[str, Any]:
    calls: list[dict] = []
    warnings: list[str] = []
    stops: list[dict] = []
    all_candidates: list[dict] = []
    demo = False
    for i, sub in enumerate(spec.get("subtasks") or []):
        res = cap.find_local_places(sub["query"], origin[0], origin[1])
        calls += res["calls"]
        demo = demo or res["demo"]
        cands = fuse(res["observations"], origin=origin)
        for c in cands:
            c["id"] = f"s{i + 1}_{c['id']}"
            c["subtask"] = sub["label"]
        all_candidates += cands
        hc = spec.get("hard_constraints") or {}
        local_spec = {"hard_constraints": {"open_now": False, "min_rating": hc.get("min_rating"),
                                           "max_distance_km": hc.get("max_distance_km")},
                      "criteria": LOCAL_CRITERIA}
        r = dec.decide([c for c in cands if c.get("lat") is not None], local_spec, now, explore=False)
        if not r["winner"]:
            warnings.append(f"No suitable place found for '{sub['label']}'.")
            continue
        by_id = {c["id"]: c for c in cands}
        chosen = by_id[r["winner"]]
        alts = [by_id[x["id"]] for x in r["ranking"][1:3]]
        cost, cost_basis = _stop_cost(chosen, sub)
        stops.append({"subtask": sub["label"], "query": sub["query"], "minutes": sub.get("est_minutes") or 15,
                      "place": _place_view(chosen), "alternatives": [_place_view(a) for a in alts],
                      "score": r["ranking"][0]["score"], "cost": cost, "cost_basis": cost_basis,
                      "candidate_id": chosen["id"]})

    destination, dcalls, dwarn = _pick_destination(spec, origin, saved_places or {})
    calls += dcalls
    warnings += dwarn

    # Order stops to minimise total travel (exhaustive for <= 7 stops, nearest-neighbour above).
    pts = [(s["place"]["lat"], s["place"]["lng"]) for s in stops]
    end = (destination["lat"], destination["lng"]) if destination else None

    def route_len(order: tuple[int, ...]) -> float:
        seq = [origin] + [pts[i] for i in order] + ([end] if end else [])
        return sum(haversine_km(*seq[k], *seq[k + 1]) for k in range(len(seq) - 1))

    idx = tuple(range(len(stops)))
    if len(stops) <= 7:
        best_order = min(itertools.permutations(idx), key=route_len) if stops else ()
    else:
        remaining, cur, best_order = set(idx), origin, ()
        while remaining:
            nxt = min(remaining, key=lambda k: haversine_km(*cur, *pts[k]))
            best_order += (nxt,)
            cur = pts[nxt]
            remaining.remove(nxt)
    stops = [stops[i] for i in best_order]

    # Legs
    seq = [origin] + [(s["place"]["lat"], s["place"]["lng"]) for s in stops] + ([end] if end else [])
    legs = [_leg(seq[k], seq[k + 1], transport) for k in range(len(seq) - 1)]
    total_travel = sum(l["minutes"] for l in legs)
    total_stop = sum(s["minutes"] for s in stops)
    total_minutes = total_travel + total_stop

    # Timeline: work backwards from arrive_by (or forwards from now).
    arrive_by = None
    if (spec.get("destination") or {}).get("arrive_by"):
        arrive_by = datetime.fromisoformat(spec["destination"]["arrive_by"])
    if arrive_by:
        start = arrive_by - timedelta(minutes=total_minutes + BUFFER_MIN)
        start = start.replace(minute=(start.minute // 5) * 5, second=0, microsecond=0)
    else:
        start = (now + timedelta(minutes=15)).replace(second=0, microsecond=0)
        start = start.replace(minute=(start.minute // 5) * 5)
    if start < now:
        late = (now - start).seconds // 60
        warnings.append(f"Not enough time: starting now you'd arrive ~{late} min late. "
                        "Consider dropping a stop or picking closer places.")
        start = (now + timedelta(minutes=5)).replace(second=0, microsecond=0)

    timeline: list[dict] = []
    event = spec.get("event") or {}
    t = start
    timeline.append({"time": t.isoformat(), "title": f"Leave {origin_label or 'home'}", "kind": "travel",
                     "detail": f"{legs[0]['mode']} · {legs[0]['km']} km · ~{legs[0]['minutes']} min" if legs else ""})
    for k, s in enumerate(stops):
        t += timedelta(minutes=legs[k]["minutes"])
        s["arrive"] = t.isoformat()
        hrs = _hours_for(s["place"].get("hours"), t)
        if hrs:
            mins = t.hour * 60 + t.minute
            if hrs == (0, 0) or not (hrs[0] <= mins < hrs[1]):
                warnings.append(f"{s['place']['name']} may be closed at {t:%I:%M %p} ({s['subtask']}). "
                                f"Check an alternative.")
                s["hours_ok"] = False
            else:
                s["hours_ok"] = True
                s["closes"] = f"{hrs[1] // 60 % 24:02d}:{hrs[1] % 60:02d}"
        timeline.append({"time": t.isoformat(), "title": s["subtask"], "kind": "stop",
                         "detail": f"{s['place']['name']} · ~₹{s['cost']:,.0f} · {s['minutes']} min",
                         "place": s["place"]})
        t += timedelta(minutes=s["minutes"])
    if destination:
        t += timedelta(minutes=legs[-1]["minutes"])
        timeline.append({"time": t.isoformat(), "title": f"Arrive at {destination['name']}", "kind": "arrive",
                         "detail": f"{legs[-1]['mode']} · {legs[-1]['km']} km"})
    if event.get("start"):
        timeline.append({"time": event["start"], "title": event.get("title") or "Event", "kind": "event", "detail": ""})
    timeline.sort(key=lambda x: x["time"])

    goods = sum(s["cost"] for s in stops)
    transport_cost = sum(l["cost"] for l in legs)
    total_cost = goods + transport_cost
    budget = (spec.get("hard_constraints") or {}).get("budget_max")
    within = None if budget is None else total_cost <= budget
    if within is False:
        warnings.append(f"Estimated total ₹{total_cost:,.0f} exceeds your ₹{budget:,.0f} budget.")
    return {
        "type": "errands", "origin": {"label": origin_label, "lat": origin[0], "lng": origin[1]},
        "destination": destination, "stops": stops, "legs": legs, "timeline": timeline,
        "totals": {"cost": total_cost, "goods": goods, "transport": transport_cost,
                   "distance_km": round(sum(l["km"] for l in legs), 2),
                   "walking_km": round(sum(l["km"] for l in legs if l["mode"] == "walk"), 2),
                   "duration_min": total_minutes, "locations": len(stops),
                   "start": start.isoformat(), "end": t.isoformat()},
        "budget": budget, "within_budget": within, "warnings": warnings,
        "calls": calls, "demo": demo, "candidates": all_candidates,
    }


def _place_view(c: dict) -> dict:
    return {"id": c["id"], "name": c["name"], "lat": c.get("lat"), "lng": c.get("lng"), "address": c.get("address"),
            "rating": dec.metric(c, "rating"), "reviews": (c["facts"].get("rating") or {}).get("reviews"),
            "distance_km": dec.metric(c, "distance"), "open_state": c.get("open_state"), "hours": c.get("hours"),
            "price_level": (c.get("attrs") or {}).get("price_level"), "url": c.get("url"),
            "phone": (c.get("attrs") or {}).get("phone")}
