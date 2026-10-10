"""Judgement on soft criteria + human-readable decision explanations."""
from __future__ import annotations

import json
import re
from typing import Any

from .. import llm
from .decision import metric

# ------------------------------------------------------------------ soft-criteria judgement
JUDGE_SYSTEM = """You rate options for DecisionOS on qualitative criteria that cannot be read off a price tag.
Use ONLY the option names/specs/snippets given plus well-established general knowledge about named models.
Score each option 0-10 per criterion. Be calibrated; if you cannot tell, give 5 and say so in the note.
Return JSON: {"scores": {"<option id>": {"<criterion>": number}}, "notes": {"<option id>": "one short sentence"}}"""

HEURISTIC_ATTRS = {
    # criterion keyword -> (attribute, direction, low, high)
    "battery": ("battery_h", "max", 4, 20),
    "portab": ("weight_kg", "min", 1.1, 2.6),
    "light": ("weight_kg", "min", 1.1, 2.6),
    "weight": ("weight_kg", "min", 1.1, 2.6),
    "ram": ("ram_gb", "max", 4, 32),
    "memory": ("ram_gb", "max", 4, 32),
}
PERF_TOKENS = [(r"\bi9\b|ryzen 9|m3|m4|rtx 40", 9), (r"\bi7\b|ryzen 7|\bm2\b|rtx 30|rtx 4050", 7.5),
               (r"\bi5\b|ryzen 5|\bm1\b", 6), (r"\bi3\b|ryzen 3|celeron|pentium|athlon", 3)]


def _heuristic_score(c: dict, crit: str) -> float | None:
    attrs = c.get("attrs") or {}
    for ext in attrs.get("extensions") or []:          # "ram gb: 16" style specs from shopping results
        m = re.match(r"\s*([a-z ]+):\s*([\d.]+)", str(ext).lower())
        if m:
            attrs.setdefault(m.group(1).strip().replace(" ", "_"), float(m.group(2)))
    for kw, (attr, direction, lo, hi) in HEURISTIC_ATTRS.items():
        if kw in crit and isinstance(attrs.get(attr), (int, float)):
            x = (float(attrs[attr]) - lo) / (hi - lo)
            x = min(1, max(0, x))
            return round(10 * (x if direction == "max" else 1 - x), 1)
    if any(k in crit for k in ("perform", "speed", "coding", "gaming", "power")):
        name = (c.get("name") or "").lower()
        for pat, s in PERF_TOKENS:
            if re.search(pat, name):
                ram = attrs.get("ram_gb")
                return min(10, s + (1 if isinstance(ram, (int, float)) and ram >= 16 else 0))
    return None


def judge(candidates: list[dict], spec: dict, context_snippets: list[str]) -> str:
    """Fill c['judgements'][name] (0-10) for every j:* criterion. Returns the method used."""
    jcrits = [c["key"][2:] for c in spec["criteria"] if c["key"].startswith("j:")]
    if not jcrits or not candidates:
        return "none"
    pool = candidates[:15]
    method = "heuristic"
    if llm.available():
        options = [{"id": c["id"], "name": c["name"], "price": metric(c, "price"),
                    "rating": metric(c, "rating"), "attrs": {k: v for k, v in (c.get("attrs") or {}).items()
                                                            if k not in ("data_id",)},
                    "snippet": (c.get("snippet") or "")[:200]} for c in pool]
        prompt = (f"User goal: {spec['goal']}\nPreferences: {spec.get('soft_preferences')}\n"
                  f"Criteria to score: {jcrits}\nOptions: {json.dumps(options, default=str)}\n"
                  f"Web context (may help): {json.dumps(context_snippets[:12])}")
        out = llm.complete_json(JUDGE_SYSTEM, prompt, max_tokens=2500)
        if isinstance(out, dict) and isinstance(out.get("scores"), dict):
            method = "claude"
            for c in pool:
                s = out["scores"].get(c["id"]) or {}
                c["judgements"] = {k: float(s[k]) for k in jcrits if isinstance(s.get(k), (int, float))}
                note = (out.get("notes") or {}).get(c["id"])
                if note:
                    c["judgement_note"] = note
    for c in candidates:
        j = c.setdefault("judgements", {})
        for k in jcrits:
            if k not in j:
                h = _heuristic_score(c, k)
                if h is not None:
                    j[k] = h
        c.setdefault("confidence", {})["judgement"] = 0.75 if method == "claude" else 0.5
    return method


# ------------------------------------------------------------------ explanation
EXPLAIN_SYSTEM = """You are the explanation layer of DecisionOS. The decision has ALREADY been made by a
transparent scoring engine; never change the winner. Explain it plainly to the user, grounded only in the
evidence provided (numbers, sources). Mention trade-offs honestly and say it is best *for their stated priorities*.
Return JSON: {"headline": "<Option> wins for you.", "summary": "2-3 sentences",
"why": ["short bullet", ...max 5], "tradeoffs": ["short bullet", ...max 3], "next_step": "one sentence"}"""


def _fmt(v: Any, currency: str = "₹") -> str:
    return f"{currency}{v:,.0f}" if isinstance(v, (int, float)) else str(v)


def explain(spec: dict, result: dict, candidates: list[dict], stats: dict) -> dict[str, Any]:
    by_id = {c["id"]: c for c in candidates}
    if not result.get("winner") and not candidates:
        return {"headline": "I couldn't find any options for this.",
                "summary": "The searches returned no usable results. Try rephrasing with the specific thing "
                           "you want (e.g. a product name or place type), or use 'Refresh research'.",
                "why": [], "tradeoffs": [], "next_step": "Rephrase the request and I'll search again.",
                "generated_by": "template"}
    if not result.get("winner"):
        return {"headline": "No option meets all your constraints.",
                "summary": "Every option found broke at least one hard constraint. "
                           "Try relaxing one of the conditions shown under 'What could change'.",
                "why": [], "tradeoffs": [], "next_step": "Adjust a constraint and I'll re-run the decision.",
                "generated_by": "template"}
    w = by_id[result["winner"]]
    top = result["ranking"][0]
    payload = {
        "goal": spec["goal"], "constraints": spec["hard_constraints"], "preferences": spec.get("soft_preferences"),
        "criteria": [{"label": c["label"], "weight": c["weight"]} for c in spec["criteria"]],
        "winner": {"name": w["name"], "score": top["score"], "facts": w["facts"], "attrs": w.get("attrs"),
                   "breakdown": top["breakdown"], "note": w.get("judgement_note"), "address": w.get("address"),
                   "open_state": w.get("open_state")},
        "alternatives": [{**a, "facts": by_id[a["id"]]["facts"]} for a in result["alternatives"]],
        "eliminated_summary": result["eliminated_summary"], "research": stats,
        "warnings": result["warnings"], "insights": result.get("insights"),
    }
    out = llm.complete_json(EXPLAIN_SYSTEM, json.dumps(payload, default=str)[:12000], max_tokens=900)
    if isinstance(out, dict) and out.get("headline"):
        out["generated_by"] = "claude"
        return out
    return _template(spec, result, w, top, by_id, stats)


def _template(spec: dict, result: dict, w: dict, top: dict, by_id: dict, stats: dict) -> dict[str, Any]:
    why = []
    b = top["breakdown"]
    strongest = sorted(b.values(), key=lambda x: -x["contribution"])[:3]
    for s in strongest:
        if s["raw"] is None:
            continue
        label = s["label"]
        if label.lower() in ("price", "cost"):
            why.append(f"{label}: {_fmt(s['raw'])}")
        elif label.lower() == "rating":
            why.append(f"Rated {s['raw']}★ from {(w['facts'].get('rating') or {}).get('reviews', 0):,} reviews")
        elif label.lower() == "distance":
            why.append(f"{s['raw']:.1f} km away")
        else:
            why.append(f"Strong on {label.lower()}")
    budget = spec["hard_constraints"].get("budget_max")
    price = metric(w, "price")
    if budget and price:
        why.append(f"{_fmt(budget - price)} under your {_fmt(budget)} budget")
    if len(w["sources"]) > 1:
        why.append(f"Verified across {len(w['sources'])} sources")
    tradeoffs = []
    for a in result["alternatives"][:2]:
        ap = a.get("price")
        diff = f" ({_fmt(ap)})" if ap else ""
        tradeoffs.append(f"{a['label']}: {a['name']}{diff}")
    return {
        "headline": f"{w['name']} wins for you.",
        "summary": f"Out of {stats.get('candidates', 0)} options from {stats.get('sources', 0)} sources, it scored "
                   f"{top['score']:.0f}/100 against your priorities "
                   f"({', '.join(c['label'].lower() for c in spec['criteria'][:3])}).",
        "why": why[:5], "tradeoffs": tradeoffs, "next_step": "Create a plan to act on this decision.",
        "generated_by": "template",
    }
