"""Decision Engine: constraint filtering + weighted multi-criteria scoring over evidence.

The score means "best according to *your stated* priorities", not objective truth (doc §11).
Everything here is deterministic so "What if?" can re-run instantly without new searches.
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

LOW_RATING = 3.5          # default "poor reviews" cut-off when the user set no min rating
LOW_RATING_MIN_REVIEWS = 20


# ------------------------------------------------------------------ metric extraction
def _delivery_days(text: str | None, now: datetime | None = None) -> float | None:
    if not text:
        return None
    t = text.lower()
    if "today" in t or "same day" in t or "hour" in t:
        return 0
    if "tomorrow" in t:
        return 1
    m = re.search(r"(\d+)\s*(?:-|–|to)\s*(\d+)\s*(?:business\s+)?days?", t)
    if m:
        return float(m.group(2))
    m = re.search(r"in\s+(\d+)\s*(?:business\s+)?days?", t)
    if m:
        return float(m.group(1))
    if now:
        days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        for i, d in enumerate(days):
            if re.search(rf"\b{d}", t):
                return float((i - now.weekday()) % 7 or 7)
    return None


def is_open(open_state: str | None) -> bool | None:
    if not open_state:
        return None
    s = open_state.lower()
    if "closed" in s and not s.startswith("open"):
        return False
    if "open" in s:
        return True
    return None


def _ago_months(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*(hour|day|week|month|year)", text.lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return n * {"hour": 1 / 720, "day": 1 / 30, "week": 0.25, "month": 1, "year": 12}[unit]


def metric(c: dict, key: str, now: datetime | None = None) -> float | None:
    f, a = c["facts"], c.get("attrs") or {}
    if key == "price":
        return (f.get("price") or {}).get("value")
    if key == "rating":
        return (f.get("rating") or {}).get("value")
    if key == "review_confidence":
        n = (f.get("rating") or {}).get("reviews")
        return math.log10(n + 1) if n is not None else None
    if key == "distance":
        return (f.get("distance_km") or {}).get("value")
    if key == "duration":
        return a.get("duration_min") or a.get("length_min")
    if key == "stops":
        return a.get("stops")
    if key == "popularity":
        v = a.get("views") or (f.get("rating") or {}).get("reviews")
        return math.log10(float(v) + 1) if v is not None else None
    if key == "recency":
        m = _ago_months(a.get("published") or a.get("date"))
        return -m if m is not None else None
    if key == "relevance":
        p = c.get("position")
        return 1 / p if p else None
    if key == "availability":
        if c["kind"] == "place":
            o = is_open(c.get("open_state"))
            return None if o is None else (1.0 if o else 0.0)
        days = _delivery_days(a.get("delivery"), now)
        return None if days is None else 1 / (1 + days)
    if key.startswith("j:"):
        return (c.get("judgements") or {}).get(key[2:])
    if key.startswith("attr:"):
        v = a.get(key[5:])
        return float(v) if isinstance(v, (int, float)) else None
    return None


# ------------------------------------------------------------------ constraints
def apply_constraints(candidates: list[dict], spec: dict, now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    hc = spec.get("hard_constraints") or {}
    budget = hc.get("budget_max")
    min_rating = hc.get("min_rating")
    max_km = hc.get("max_distance_km")
    must = [m.lower() for m in hc.get("must_include") or []]
    deadline = None
    if hc.get("deadline"):
        try:
            deadline = datetime.fromisoformat(hc["deadline"])
        except ValueError:
            pass
    keep, out = [], []
    for c in candidates:
        reasons = []
        price = metric(c, "price")
        if budget and price and price > budget:
            reasons.append(("over_budget", f"Over budget ({price:,.0f} > {budget:,.0f})"))
        rating = metric(c, "rating")
        reviews = (c["facts"].get("rating") or {}).get("reviews") or 0
        if min_rating and rating is not None and rating < min_rating:
            reasons.append(("poor_reviews", f"Rating {rating} below your minimum {min_rating}"))
        elif not min_rating and rating is not None and rating < LOW_RATING and reviews >= LOW_RATING_MIN_REVIEWS:
            reasons.append(("poor_reviews", f"Poor reviews ({rating}★ from {reviews:,})"))
        dist = metric(c, "distance")
        if max_km and dist is not None and dist > max_km:
            reasons.append(("too_far", f"{dist:.1f} km away (limit {max_km:g} km)"))
        if hc.get("open_now") and is_open(c.get("open_state")) is False:
            reasons.append(("closed", "Closed right now"))
        if must and not all(m in (c["name"] or "").lower() for m in must):
            reasons.append(("missing_requirement", f"Doesn't match required: {', '.join(must)}"))
        if deadline and now and c["kind"] == "product":
            days = _delivery_days((c.get("attrs") or {}).get("delivery"), now)
            if days is not None and (now.date().toordinal() + days) > deadline.date().toordinal():
                reasons.append(("unavailable", f"Won't arrive before {deadline:%a %d %b}"))
        if reasons:
            out.append({"id": c["id"], "name": c["name"], "price": price,
                        "codes": [r[0] for r in reasons], "reasons": [r[1] for r in reasons]})
        else:
            keep.append(c)
    return keep, out


# ------------------------------------------------------------------ scoring
def score(candidates: list[dict], criteria: list[dict], now: datetime | None = None) -> list[dict]:
    rows = []
    stats: dict[str, tuple[float, float]] = {}
    for cr in criteria:
        vals = [v for v in (metric(c, cr["key"], now) for c in candidates) if v is not None]
        if vals:
            stats[cr["key"]] = (min(vals), max(vals))
    for c in candidates:
        breakdown, total, missing = {}, 0.0, []
        for cr in criteria:
            raw = metric(c, cr["key"], now)
            if raw is None or cr["key"] not in stats:
                norm = 0.5                 # neutral when unknown, flagged below
                missing.append(cr["label"])
            else:
                lo, hi = stats[cr["key"]]
                norm = 1.0 if hi == lo else (raw - lo) / (hi - lo)
                if cr["direction"] == "min":
                    norm = 1.0 - norm if hi != lo else 1.0
            contrib = cr["weight"] * norm
            total += contrib
            breakdown[cr["key"]] = {"label": cr["label"], "raw": raw, "norm": round(norm, 3),
                                    "weight": cr["weight"], "contribution": round(contrib, 4)}
        rows.append({"id": c["id"], "name": c["name"], "score": round(total * 100, 1),
                     "breakdown": breakdown, "missing": missing})
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    return rows


def _alternatives(survivors: list[dict], ranking: list[dict], criteria: list[dict], winner_id: str) -> list[dict]:
    alts: list[dict] = []
    seen = {winner_id}
    by_id = {c["id"]: c for c in survivors}

    def add(label: str, cid: str | None, why: str):
        if cid and cid not in seen:
            seen.add(cid)
            alts.append({"label": label, "id": cid, "name": by_id[cid]["name"], "why": why,
                         "price": metric(by_id[cid], "price")})

    priced = [c for c in survivors if metric(c, "price") is not None]
    if priced:
        ch = min(priced, key=lambda c: metric(c, "price"))
        add("Cheapest", ch["id"], "Lowest price among options that meet your constraints")
    rated = [c for c in survivors if metric(c, "rating") is not None]
    if rated:
        top = max(rated, key=lambda c: (metric(c, "rating"), (c["facts"].get("rating") or {}).get("reviews", 0)))
        add("Highest rated", top["id"], "Best review score")
    for cr in sorted(criteria, key=lambda c: -c["weight"]):
        if cr["key"] in ("price", "rating"):
            continue
        vals = [(metric(c, cr["key"]), c) for c in survivors if metric(c, cr["key"]) is not None]
        if vals:
            best = (min if cr["direction"] == "min" else max)(vals, key=lambda t: t[0])[1]
            add(f"Best {cr['label'].lower()}", best["id"], f"Strongest on {cr['label'].lower()}")
        if len(alts) >= 3:
            break
    if len(alts) < 2 and len(ranking) > 1:
        add("Runner-up", ranking[1]["id"], "Second-highest overall score")
    return alts


def decide(candidates: list[dict], spec: dict, now: datetime | None = None, explore: bool = True) -> dict[str, Any]:
    survivors, eliminated = apply_constraints(candidates, spec, now)
    criteria = spec["criteria"]
    ranking = score(survivors, criteria, now)
    summary: dict[str, int] = {}
    for e in eliminated:
        for code in e["codes"]:
            summary[code] = summary.get(code, 0) + 1
    result: dict[str, Any] = {
        "winner": ranking[0]["id"] if ranking else None,
        "ranking": ranking, "eliminated": eliminated, "eliminated_summary": summary,
        "criteria": criteria, "alternatives": [], "what_could_change": [], "warnings": [],
        "insights": [],
    }
    if not ranking:
        if eliminated:
            result["warnings"].append("No option satisfies all your hard constraints. See what could change below.")
        if explore:
            result["what_could_change"] = _what_could_change(candidates, spec, None, now)
        return result
    by_id = {c["id"]: c for c in candidates}
    winner = by_id[ranking[0]["id"]]
    result["alternatives"] = _alternatives(survivors, ranking, criteria, winner["id"])
    result["warnings"] = list(winner.get("warnings") or [])
    if ranking[0]["missing"]:
        result["warnings"].append(f"Missing data for {', '.join(ranking[0]['missing'])} on the top option; "
                                  "it was scored as average on those.")
    if len(ranking) > 1 and ranking[0]["score"] - ranking[1]["score"] < 3:
        result["warnings"].append(f"Close call: {ranking[1]['name']} scored within "
                                  f"{ranking[0]['score'] - ranking[1]['score']:.1f} points.")
    price = winner["facts"].get("price")
    if price and len(price["values"]) > 1 and price["spread_pct"] > 2:
        lo, hi = price["values"][0], price["values"][-1]
        result["insights"].append({
            "type": "cheaper_elsewhere",
            "text": f"Don't buy the {hi['source']} listing yet — the same item is {hi['value'] - lo['value']:,.0f} cheaper at {lo['source']}.",
        })
    if explore:
        result["what_could_change"] = _what_could_change(candidates, spec, winner["id"], now)
    return result


def _what_could_change(candidates: list[dict], spec: dict, winner_id: str | None, now: datetime | None) -> list[dict]:
    changes: list[dict] = []
    budget = (spec.get("hard_constraints") or {}).get("budget_max")
    by_id = {c["id"]: c for c in candidates}
    if budget:
        over = sorted((c for c in candidates if (metric(c, "price") or 0) > budget), key=lambda c: metric(c, "price"))
        for c in over[:6]:
            s2 = deepcopy(spec)
            s2["hard_constraints"]["budget_max"] = metric(c, "price")
            r = decide(candidates, s2, now, explore=False)
            if r["winner"] and r["winner"] != winner_id:
                changes.append({"kind": "budget", "condition": f"Budget raised to {metric(c, 'price'):,.0f}",
                                "patch": {"hard_constraints": {"budget_max": metric(c, "price")}},
                                "winner": r["winner"], "winner_name": by_id[r["winner"]]["name"]})
                break
    for cr in spec["criteria"]:
        if len(spec["criteria"]) < 2:
            break
        s2 = deepcopy(spec)
        for c2 in s2["criteria"]:
            c2["weight"] = c2["weight"] * (3 if c2["key"] == cr["key"] else 1)
        tot = sum(c2["weight"] for c2 in s2["criteria"])
        for c2 in s2["criteria"]:
            c2["weight"] = c2["weight"] / tot
        r = decide(candidates, s2, now, explore=False)
        if r["winner"] and r["winner"] != winner_id:
            changes.append({"kind": "priority", "condition": f"If {cr['label'].lower()} mattered much more",
                            "patch": {"boost": cr["key"]}, "winner": r["winner"],
                            "winner_name": by_id[r["winner"]]["name"]})
    return changes[:4]


def apply_patch(spec: dict, patch: dict) -> dict:
    """Apply a what-if patch: {hard_constraints:{...}, weights:{key:w}, boost:key, add_criteria:[...]}"""
    s = deepcopy(spec)
    for k, v in (patch.get("hard_constraints") or {}).items():
        s["hard_constraints"][k] = v
    weights = patch.get("weights") or {}
    if patch.get("boost"):
        weights = {c["key"]: c["weight"] * (3 if c["key"] == patch["boost"] else 1) for c in s["criteria"]}
    for add in patch.get("add_criteria") or []:
        if not any(c["key"] == add["key"] for c in s["criteria"]):
            s["criteria"].append({"key": add["key"], "label": add.get("label", add["key"]),
                                  "weight": add.get("weight", 0.3),
                                  "direction": add.get("direction", "max")})
    for c in s["criteria"]:
        if c["key"] in weights:
            c["weight"] = float(weights[c["key"]])
    tot = sum(c["weight"] for c in s["criteria"]) or 1
    for c in s["criteria"]:
        c["weight"] = round(c["weight"] / tot, 4)
    return s
