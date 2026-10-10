"""Claude-assisted synthesis for decision types whose options are not directly listed by an API:
- travel: ground options (train/bus/car) extracted from search snippets, labelled as estimates
- knowledge: candidate research directions grounded in papers / patents / news
- video: a non-redundant learning path from the ranked videos
Each has a deterministic fallback.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import llm
from ..serp.capabilities import _obs  # shared observation constructor


def _snips(observations: list[dict], kinds: tuple[str, ...] = ("article",), n: int = 14) -> list[dict]:
    return [{"i": i, "title": o["name"], "source": o["source"], "snippet": (o.get("snippet") or "")[:280],
             "url": o.get("url"), **({"cited_by": o["attrs"].get("cited_by")} if o.get("attrs", {}).get("cited_by") else {})}
            for i, o in enumerate(o for o in observations if o["kind"] in kinds)][:n]


# ------------------------------------------------------------------ travel
GROUND_SYSTEM = """Extract ground transport options between two Indian cities from web snippets for DecisionOS.
Use the snippets first; you may fill typical values from general knowledge but then set "estimated": true.
Return JSON: {"options": [{"mode": "train"|"bus"|"car"|"cab", "name": str, "price": number (INR, typical one-way fare),
"duration_min": number, "notes": str, "estimated": bool, "source_index": number|null}]} (max 4 options)."""


def ground_options(route: dict, observations: list[dict]) -> tuple[list[dict], str]:
    snips = _snips(observations)
    out = llm.complete_json(GROUND_SYSTEM, json.dumps({"route": route, "snippets": snips}), max_tokens=900)
    obs: list[dict] = []
    if isinstance(out, dict):
        for o in out.get("options") or []:
            if not isinstance(o, dict) or not o.get("price"):
                continue
            src_i = o.get("source_index")
            src = snips[src_i] if isinstance(src_i, int) and 0 <= src_i < len(snips) else None
            obs.append(_obs(kind="flight", name=f"{o.get('mode', 'ground').title()}: {o.get('name', '')}".strip(": "),
                            source=f"Estimate · {src['source']}" if src else "Estimate", engine="estimate",
                            url=src["url"] if src else None, price=float(o["price"]),
                            snippet=o.get("notes"),
                            attrs={"mode": o.get("mode"), "duration_min": o.get("duration_min"), "stops": 0,
                                   "estimated": True}))
        return obs, "claude"
    return _ground_from_ai_mode(route)


def _ground_from_ai_mode(route: dict) -> tuple[list[dict], str]:
    """No Claude: ask Google AI Mode for train/bus options and parse fares + durations from its answer."""
    from ..serp import capabilities as cap
    if not route.get("from") or not route.get("to"):
        return [], "unavailable"
    res = cap.ask_ai_mode(f"train and bus options from {route['from']} to {route['to']} with ticket price and travel time")
    text = next((o["snippet"] for o in res["observations"] if (o.get("attrs") or {}).get("ai_answer")), "") or ""
    ref = next((o for o in res["observations"] if (o.get("attrs") or {}).get("ai_reference")), None)
    obs = []
    for t in cap.parse_transport_options(text):
        if not t["cost_low"] or t["per_vehicle"] or re.search(r"flight", t["mode"], re.I):
            continue
        obs.append(_obs(kind="flight", name=t["label"], source="Google AI Mode" + (f" · {ref['source']}" if ref else ""),
                        engine="google_ai_mode", url=ref.get("url") if ref else None,
                        price=(t["cost_low"] + (t["cost_high"] or t["cost_low"])) / 2, snippet=t["detail"],
                        attrs={"mode": "train" if re.search(r"train|express|shatabdi|vande", t["mode"], re.I) else "bus",
                               "duration_min": t["hours"] * 60 if t["hours"] else None, "stops": 0, "estimated": True,
                               "fare_range": f"₹{t['cost_low']:,.0f}–₹{(t['cost_high'] or t['cost_low']):,.0f}"}))
    return obs, ("google_ai_mode" if obs else "unavailable")


# ------------------------------------------------------------------ knowledge
KNOWLEDGE_SYSTEM = """You are the research analyst of DecisionOS. From the papers, patents, news and web results
provided, propose 3-5 distinct, concrete directions the user could pursue. Ground each in the sources (cite by index).
Score each 0-10 on: promise (impact/novelty/trend), feasibility (for this user: assume a B.Tech student with a laptop
unless the request says otherwise), evidence (how well the sources support the gap).
Return JSON: {"landscape": {"established": [str], "emerging": [str], "gaps": [str]},
"directions": [{"name": str, "summary": str, "why_now": str, "sources": [indices], "promise": n, "feasibility": n, "evidence": n}]}"""


def research_directions(goal: str, observations: list[dict]) -> tuple[list[dict], dict, str]:
    snips = _snips(observations, kinds=("paper", "article"), n=24)
    out = llm.complete_json(KNOWLEDGE_SYSTEM, json.dumps({"goal": goal, "sources": snips}), max_tokens=2200)
    if isinstance(out, dict) and out.get("directions"):
        cands = []
        for i, d in enumerate(out["directions"]):
            srcs = [snips[k] for k in d.get("sources") or [] if isinstance(k, int) and 0 <= k < len(snips)]
            cands.append({
                "id": f"d{i + 1}", "name": d.get("name"), "kind": "direction", "url": srcs[0]["url"] if srcs else None,
                "thumbnail": None, "sources": list(dict.fromkeys(s["source"] for s in srcs)) or ["Claude synthesis"],
                "observation_count": len(srcs), "facts": {}, "lat": None, "lng": None, "address": None,
                "hours": None, "open_state": None, "position": i + 1, "best_offer": None,
                "snippet": d.get("summary"), "attrs": {"why_now": d.get("why_now"),
                                                       "evidence": [{"title": s["title"], "url": s["url"], "source": s["source"]} for s in srcs]},
                "judgements": {"promise": _n(d.get("promise")), "feasibility": _n(d.get("feasibility")),
                               "evidence": _n(d.get("evidence"))},
                "confidence": {"identity": 0.8, "judgement": 0.7}, "warnings": [], "estimated": True,
            })
        return cands, out.get("landscape") or {}, "claude"
    return [], {}, "unavailable"


def _n(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ video
PATH_SYSTEM = """Build a short learning path from these YouTube videos for DecisionOS. Remove redundant videos
(same scope), order from fundamentals to advanced, max 7 items, one per day. Use only the given videos.
Return JSON: {"title": "N-Day <Topic> Plan", "items": [{"id": "<candidate id>", "focus": "what this day covers"}]}"""

LEVEL_HINTS = [("100 seconds", 0), ("explained", 1), ("beginner", 1), ("crash course", 2), ("full course", 2),
               ("tutorial", 3), ("project", 4), ("best practice", 5), ("advanced", 6), ("interview", 7)]


def learning_path(topic: str, ranked: list[dict]) -> dict[str, Any]:
    vids = [{"id": c["id"], "title": c["name"], "channel": c["attrs"].get("channel"),
             "length_min": c["attrs"].get("length_min"), "views": c["attrs"].get("views")} for c in ranked[:12]]
    by_id = {c["id"]: c for c in ranked}
    out = llm.complete_json(PATH_SYSTEM, json.dumps({"topic": topic, "videos": vids}), max_tokens=900)
    items = []
    if isinstance(out, dict) and out.get("items"):
        for it in out["items"]:
            c = by_id.get(it.get("id"))
            if c:
                items.append({"id": c["id"], "title": c["name"], "url": c.get("url"), "focus": it.get("focus", ""),
                              "length_min": c["attrs"].get("length_min"), "channel": c["attrs"].get("channel")})
        title = out.get("title")
    else:
        def level(c: dict) -> int:
            n = c["name"].lower()
            return next((lvl for k, lvl in LEVEL_HINTS if k in n), 3)
        seen_levels, picked = set(), []
        for c in sorted(ranked[:10], key=level):
            lv = level(c)
            if lv in seen_levels:
                continue
            seen_levels.add(lv)
            picked.append(c)
        items = [{"id": c["id"], "title": c["name"], "url": c.get("url"),
                  "focus": re.sub(r".*?(full course|crash course|tutorial|explained|advanced|best practices|"
                                  r"interview questions|in 100 seconds).*", r"\1", c["name"], flags=re.I),
                  "length_min": c["attrs"].get("length_min"), "channel": c["attrs"].get("channel")}
                 for c in picked[:7]]
        title = None
    return {"title": title or f"{len(items)}-Day {topic.title()} Plan", "items": items}
