"""Evidence Engine: observations -> fused, source-attributed candidates with confidence.

Steps (design doc §10): collect, dedupe, normalise, detect contradictions, score source
reliability, extract facts, attach sources. The output is the only thing the decision engine
ranks, so every number in a recommendation can be traced back to a source.
"""
from __future__ import annotations

import math
import re
from statistics import median
from typing import Any

SOURCE_RELIABILITY = {
    "amazon": 0.9, "google_shopping": 0.85, "google_maps": 0.9, "google_flights": 0.92, "google_hotels": 0.85,
    "ebay": 0.7, "walmart": 0.85, "google_lens": 0.6, "youtube": 0.8, "google_scholar": 0.9,
    "google_patents": 0.85, "google_news": 0.75, "google": 0.55, "google_jobs": 0.75, "estimate": 0.4,
    "google_ai_mode": 0.5, "bing_copilot": 0.45, "google_ai_overview": 0.5, "airbnb": 0.8, "tripadvisor": 0.75,
    "google_events": 0.8, "google_finance": 0.9, "google_finance_markets": 0.9, "google_trends": 0.8,
    "google_travel_explore": 0.85, "google_maps_reviews": 0.8, "google_hotels_reviews": 0.8, "bing": 0.55,
    "bing_news": 0.7, "duckduckgo": 0.5, "yahoo": 0.5, "google_play": 0.85, "apple_app_store": 0.85,
}

STOP = {"for", "with", "and", "the", "men", "mens", "women", "womens", "s", "new", "latest", "edition", "of", "in",
        "by", "a", "an", "to", "black", "white", "blue", "grey", "gray", "silver", "laptop", "inch", "cm", "windows",
        "11", "home", "free", "pack", "combo", "online", "india", "official", "warranty", "year", "years"}


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (name or "").lower()) if t not in STOP and len(t) > 1}


def _model_tokens(toks: set[str]) -> set[str]:
    return {t for t in toks if re.search(r"\d", t) and re.search(r"[a-z]", t)}


def same_product(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    ma, mb = _model_tokens(ta), _model_tokens(tb)
    if ma and mb and not (ma & mb):
        return False            # different model numbers -> different products
    containment = len(ta & tb) / min(len(ta), len(tb))
    return containment >= 0.7


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _rel(engine: str | None) -> float:
    return SOURCE_RELIABILITY.get(engine or "", 0.5)


def _cluster(observations: list[dict]) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for o in observations:
        if not o.get("name"):
            continue
        placed = False
        for cl in clusters:
            head = cl[0]
            if head["kind"] != o["kind"]:
                continue
            if o["kind"] == "product" and same_product(head["name"], o["name"]):
                placed = True
            elif o["kind"] == "place" and (
                    (o.get("id") and o.get("id") == head.get("id")) or
                    (same_product(head["name"], o["name"]) and o.get("lat") is not None and head.get("lat") is not None
                     and haversine_km(o["lat"], o["lng"], head["lat"], head["lng"]) < 0.3)):
                placed = True
            elif o["kind"] in ("video", "article", "paper", "job") and o.get("url") and o.get("url") == head.get("url"):
                placed = True
            if placed:
                cl.append(o)
                break
        if not placed:
            clusters.append([o])
    return clusters


def _price_fact(cluster: list[dict], currency: str) -> tuple[dict | None, list[str]]:
    vals = [{"source": o["source"], "value": o["price"], "url": o.get("url"), "engine": o["engine"]}
            for o in cluster if o.get("price") and (o.get("currency") or currency) == currency]
    if not vals:
        return None, []
    prices = [v["value"] for v in vals]
    lo, hi = min(prices), max(prices)
    spread = (hi - lo) / lo if lo else 0.0
    rel = max(_rel(v["engine"]) for v in vals)
    if len(vals) == 1:
        conf = rel * 0.9
    elif spread <= 0.05:
        conf = min(0.97, rel + 0.08)
    else:
        conf = max(0.55, rel - min(0.3, spread))
    warnings = []
    if len(vals) > 1 and spread > 0.05:
        cheapest = min(vals, key=lambda v: v["value"])
        dearest = max(vals, key=lambda v: v["value"])
        warnings.append(
            f"Price uncertainty: {dearest['source']} lists {currency} {dearest['value']:,.0f} while "
            f"{cheapest['source']} lists {currency} {cheapest['value']:,.0f}. Verify the final checkout price.")
    return {"value": lo, "median": median(prices), "values": sorted(vals, key=lambda v: v["value"]),
            "confidence": round(conf, 2), "spread_pct": round(spread * 100, 1)}, warnings


def _rating_fact(cluster: list[dict]) -> dict | None:
    pts = [(float(o["rating"]), int(o.get("reviews") or 0), o["source"]) for o in cluster if o.get("rating")]
    if not pts:
        return None
    total = sum(max(n, 1) for _, n, _ in pts)
    avg = sum(r * max(n, 1) for r, n, _ in pts) / total
    reviews = sum(n for _, n, _ in pts)
    conf = min(0.97, 0.45 + math.log10(reviews + 1) / 7)
    if len(pts) > 1 and max(r for r, _, _ in pts) - min(r for r, _, _ in pts) > 0.5:
        conf -= 0.15
    return {"value": round(avg, 2), "values": [{"source": s, "value": r, "reviews": n} for r, n, s in pts],
            "reviews": reviews, "confidence": round(max(conf, 0.3), 2)}


def fuse(observations: list[dict], currency: str = "INR", origin: tuple[float, float] | None = None) -> list[dict]:
    candidates = []
    for i, cl in enumerate(_cluster(observations)):
        cl.sort(key=lambda o: -_rel(o["engine"]))
        head = cl[0]
        name = min((o["name"] for o in cl), key=len) if head["kind"] == "product" else head["name"]
        facts: dict[str, Any] = {}
        warnings: list[str] = []
        price, w = _price_fact(cl, currency)
        if price:
            facts["price"] = price
        warnings += w
        rating = _rating_fact(cl)
        if rating:
            facts["rating"] = rating
        attrs: dict[str, Any] = {}
        for o in reversed(cl):          # most reliable source wins on conflicts
            attrs.update({k: v for k, v in (o.get("attrs") or {}).items() if v not in (None, "", [])})
        lat = next((o["lat"] for o in cl if o.get("lat") is not None), None)
        lng = next((o["lng"] for o in cl if o.get("lng") is not None), None)
        if origin and lat is not None and lng is not None:
            d = haversine_km(origin[0], origin[1], lat, lng)
            facts["distance_km"] = {"value": round(d, 2), "confidence": 0.9, "values": [{"source": "computed", "value": round(d, 2)}]}
        positions = [o["position"] for o in cl if isinstance(o.get("position"), (int, float))]
        sources = list(dict.fromkeys(o["source"] for o in cl if o.get("source")))
        identity_conf = 0.97 if len(cl) > 1 or head.get("id") else 0.85
        best_offer = None
        if price:
            v0 = price["values"][0]
            best_offer = {"source": v0["source"], "price": v0["value"], "url": v0.get("url")}
        candidates.append({
            "id": f"c{i + 1}", "name": name, "kind": head["kind"], "url": head.get("url"),
            "thumbnail": next((o["thumbnail"] for o in cl if o.get("thumbnail")), None),
            "sources": sources, "observation_count": len(cl), "facts": facts, "attrs": attrs,
            "lat": lat, "lng": lng, "address": head.get("address"), "hours": head.get("hours"),
            "open_state": head.get("open_state"), "snippet": head.get("snippet"),
            "position": min(positions) if positions else None, "best_offer": best_offer,
            "confidence": {"identity": identity_conf,
                           **({"price": price["confidence"]} if price else {}),
                           **({"reviews": rating["confidence"]} if rating else {})},
            "warnings": warnings, "estimated": head["engine"] == "estimate",
        })
    return candidates


def summarize(candidates: list[dict], calls: list[dict]) -> dict[str, Any]:
    sources = {s.split(" · ")[-1] for c in candidates for s in c["sources"]}
    return {
        "candidates": len(candidates),
        "sources": len(sources),
        "source_names": sorted(sources)[:20],
        "reviews": sum((c["facts"].get("rating") or {}).get("reviews", 0) for c in candidates),
        "searches": len(calls),
        "failed_searches": sum(1 for c in calls if not c.get("ok")),
        "cross_verified": sum(1 for c in candidates if len(c["sources"]) > 1),
    }
