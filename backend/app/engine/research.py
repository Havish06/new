"""Research planner + executor for open-ended questions (any query that isn't one of the typed
decision flows).

  query -> PLAN (which registry tools, with which args, and why; what's missing/assumed)
        -> EXECUTE (parallel, with per-tool fallbacks)
        -> EVIDENCE (numbered, source-attributed, each value labelled with how far it is verified)
        -> ANSWER (Claude writes only from the evidence; deterministic fallback otherwise)

The plan is stored on the decision and shown to the user before/while it runs, so DecisionOS
states explicitly what it is going to do for a query.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import llm
from ..serp import registry

_TASK_POOL = ThreadPoolExecutor(max_workers=6)   # separate from the engine-call pool to avoid nested waits
MAX_TASKS = 6

PLAN_SYSTEM = """You are the research planner of DecisionOS. Decide what has to be done to answer the user's
request well, using ONLY these tools (each one is a live search API):
{catalog}

Rules:
- Pick the smallest set of tools that fully answers the request (1-{max_tasks} tasks). Never add tools "just in case":
  no images unless they want to see pictures, no news unless freshness matters, no finance unless it's about markets.
- Include ai_answer whenever the user wants an explanation, plan, itinerary, how-to, comparison or advice.
- Prefer specialised tools over web_search when one fits (stays for hotel prices, local_places for nearby places,
  events for things happening, finance for quotes, apps for apps, jobs for openings, trends for popularity).
- Write good search queries: short, specific, no budget numbers or filler words.
- If an important detail is missing (e.g. travel dates, city), still plan with a sensible assumption, list it in
  "assumptions", and put one short question in "clarifying_question".
Return JSON: {{"intent": "short label", "summary": "one sentence: what you will do",
 "tasks": [{{"tool": name, "args": {{...}}, "purpose": "what this task finds"}}],
 "assumptions": [str], "missing_info": [str], "clarifying_question": str|null}}"""


# ------------------------------------------------------------------ planning
def make_plan(query: str, spec: dict, context: dict, now) -> dict[str, Any]:
    out = llm.complete_json(PLAN_SYSTEM.format(catalog=registry.catalog(), max_tasks=MAX_TASKS),
                            f"Current time: {now:%A %Y-%m-%d %H:%M}\nUser location: {context.get('location_label')}\n"
                            f"Request: {query}", max_tokens=1200)
    if isinstance(out, dict) and isinstance(out.get("tasks"), list):
        tasks, rejected = _validated(out["tasks"])
        if tasks:
            return {"intent": out.get("intent") or "research", "summary": out.get("summary") or "",
                    "tasks": tasks, "rejected": rejected,
                    "assumptions": [a for a in out.get("assumptions") or [] if isinstance(a, str)],
                    "missing_info": [m for m in out.get("missing_info") or [] if isinstance(m, str)],
                    "clarifying_question": out.get("clarifying_question"), "planned_by": "claude"}
    return rule_plan(query, spec, context)


def _validated(raw: list) -> tuple[list[dict], list[str]]:
    tasks, rejected, seen = [], [], set()
    for t in raw:
        if not isinstance(t, dict):
            continue
        args, err = registry.validate(str(t.get("tool")), t.get("args"))
        if err:
            rejected.append(err)
            continue
        key = (t["tool"], json.dumps(args, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        tasks.append({"id": f"t{len(tasks) + 1}", "tool": t["tool"], "args": args,
                      "purpose": t.get("purpose") or registry.TOOLS[t["tool"]].purpose, "status": "planned"})
        if len(tasks) >= MAX_TASKS:
            break
    return tasks, rejected


FINANCE_SYMBOLS = {r"\bnifty\b": "NIFTY_50:INDEXNSE", r"\bsensex\b": "SENSEX:INDEXBOM",
                   r"\bbitcoin|\bbtc\b": "BTC-INR", r"\bethereum|\beth\b": "ETH-INR",
                   r"\b(?:usd|dollar)\b.*\b(?:inr|rupee)": "USD-INR", r"\bgold\b": "GCW00:COMEX"}
FILLER = r"\b(please|can you|could you|tell me|i want to know|i need|i want|show me|find me|find|suggest me|suggest|" \
         r"what are|what is|what's|what|which|are there|are|is there|any|give me|list|some|good|me|a|an|the|for me)\b"


def _clean(q: str) -> str:
    s = re.sub(r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?\s*(?:k|thousand|lakh)?", " ", q, flags=re.I)
    s = re.sub(r"\bnear me\b", "near_ME", s, flags=re.I)        # keep "near me" for map searches
    s = re.sub(FILLER, " ", s, flags=re.I).replace("near_ME", "near me")
    return " ".join(re.sub(r"[?!.,]", " ", s).split()) or q


def _city(context: dict) -> str:
    return re.split(r"[,(]", context.get("location_label") or "")[0].strip()


def rule_plan(query: str, spec: dict, context: dict) -> dict[str, Any]:
    """Deterministic routing table used when Claude is unavailable (and as the tested baseline)."""
    ql, q = query.lower(), _clean(query)
    city = _city(context)
    mentions_place = bool(re.search(r"\b(in|near|at|around)\s+[A-Za-z]", query))
    where = q if mentions_place or not city else f"{q} {city}"
    tasks: list[dict] = []
    assumptions: list[str] = []
    question = None

    def add(tool: str, args: dict, purpose: str):
        if len(tasks) < MAX_TASKS and not any(t["tool"] == tool and t["args"] == args for t in tasks):
            tasks.append({"id": f"t{len(tasks) + 1}", "tool": tool, "args": args, "purpose": purpose, "status": "planned"})

    # A written, source-linked answer from Google AI Mode for every question ("near me" made explicit).
    ai_q = re.sub(r"\bnear me\b|\bnearby\b", f"near {city}" if city else "near me", query, flags=re.I).strip()
    add("ai_answer", {"q": ai_q}, "Written answer with sources (Google AI Mode)")

    if re.search(r"\b(stock market|share market|markets? (?:today|now)|how (?:is|are) (?:the )?markets?|sensex and nifty|"
                 r"global markets?)\b", ql):
        add("markets", {}, "Major indexes, currencies and crypto right now")
    if re.search(r"\b(what'?s trending|trending (?:now|today|topics|searches)|what are people searching)\b", ql):
        add("trending_now", {"hours": "24"}, "What people are searching for right now")
    if re.search(r"\b(reviews? (?:of|for)|what do people say about)\b", ql) and \
            not re.search(r"\b(phone|laptop|headphones?|book|movie|app|car|bike|course)\b", ql):
        add("place_reviews", {"q": _clean(re.sub(r"\b(reviews? (?:of|for)|what do people say about)\b", " ", ql))},
            "What reviewers say about this place")
    if not any(t["tool"] == "markets" for t in tasks) and re.search(r"\b(stocks?|shares?|share price|nifty|sensex|nasdaq|market cap|ticker|bitcoin|btc|crypto|ethereum|"
                 r"exchange rate|usd to inr|dollar rate|gold rate)\b", ql):
        sym = next((v for pat, v in FINANCE_SYMBOLS.items() if re.search(pat, ql)), None)
        if not sym:
            m = re.search(r"\b([A-Z]{2,10})\b", query)
            sym = f"{m.group(1)}:NSE" if m and m.group(1) not in ("USD", "INR", "AI") else None
        if sym:
            add("finance", {"symbol": sym}, "Live quote and key stats")
        else:
            add("web_search", {"q": f"{q} share price today"}, "Current price from the web")
        add("news_search", {"q": q}, "Recent news that moves the price")
    if re.search(r"\b(events?|concerts?|gigs?|meetups?|happening|stand ?up|comedy shows?|festivals?|exhibitions?|"
                 r"workshops?|things to do this (?:weekend|week))\b", ql):
        when = next((w for w in ("today", "tomorrow", "weekend", "next_week", "next_month", "month", "week")
                     if w.replace("_", " ") in ql), None)
        ev_q = _clean(re.sub(r"\b(happening|going on|this weekend|next weekend|weekend|today|tomorrow|tonight|this week|"
                             r"next week|this month|next month|upcoming)\b", " ", where, flags=re.I))
        add("events", {"q": ev_q, **({"when": when} if when else {})}, "Upcoming events with dates and venues")
    if re.search(r"\b(jobs?|hiring|vacanc\w*|internships?|openings?|careers?)\b", ql):
        loc = re.search(r"\b(?:in|at|near)\s+([a-z]+(?:\s[a-z]+)?)\s*$|\b(?:in|at|near)\s+([a-z]+)", ql)
        place = (loc.group(1) or loc.group(2)).title() if loc else city
        role = _clean(re.sub(r"\b(?:in|at|near)\s+" + re.escape(place.lower()) + r"\b", " ", ql)) if loc else q
        add("jobs", {"q": role, **({"location": place} if place else {})}, "Current job openings")
    if re.search(r"\b(apps?|play store|app store)\b", ql):
        add("apps", {"q": q}, "Apps with ratings from both stores")
    if re.search(r"\b(pictures?|photos?|images?|looks? like)\b", ql) and not re.search(r"passport", ql):
        add("images", {"q": _clean(re.sub(r"\b(show me|pictures?|photos?|images?|of|looks? like|how does|what does)\b",
                                            " ", ql))}, "Pictures")
    if re.search(r"\b(trend(?:ing|s)?|popularity|popular (?:right )?now|search interest)\b", ql) \
            and not any(t["tool"] == "trending_now" for t in tasks):
        term = _clean(re.sub(r"\b(is|are|trending|trends?|popular(?:ity)?|right now|now|search interest|getting|"
                             r"becoming|how|in india|these days|or not|more|less|which)\b", " ", ql))
        term = ",".join(p.strip() for p in re.split(r"\s(?:or|vs\.?|versus|and)\s", term) if p.strip())
        add("trends", {"q": term}, "Search interest over the last 12 months")
    if re.search(r"\b(hotels?|stays?|hostels?|homestays?|resorts?|airbnb|accommodation|lodges?|guest ?houses?)\b", ql):
        add("stays", {"q": where}, "Stays with prices for specific dates")
        assumptions.append("No dates given — prices are for a 1-night stay next week.")
        question = "Which dates (and how many people) should I price the stay for?"
    if re.search(r"\b(restaurants?|food|eat|cafes?|dinner|lunch|breakfast|street food|biryani|momos|dosa|bakery)\b", ql):
        add("local_places", {"q": where}, "Nearby places with ratings, reviews and hours")
        add("tripadvisor", {"q": where, "category": "restaurants"}, "Restaurant reputation from Tripadvisor")
    if re.search(r"\b(things to do|attractions?|sightseeing|places to visit|tourist (?:places|spots)|must see)\b", ql):
        add("tripadvisor", {"q": where, "category": "things_to_do"}, "Top things to do from Tripadvisor")
    if re.search(r"\b(news|latest|today'?s|this week|recent(?:ly)?|updates?|announced?|launch(?:ed)?)\b", ql):
        add("news_search", {"q": q}, "Latest coverage with dates")
    if re.search(r"\b(videos?|youtube|tutorials?|how to .* video)\b", ql):
        add("videos", {"q": q}, "Relevant videos")
    if re.search(r"\b(papers?|research(?:ers)?|studies|study on|journals?|thesis|patents?)\b", ql):
        add("scholar", {"q": q}, "Papers, patents and news")
    if re.search(r"\b(buy|price of|cheapest|deals?|discount)\b", ql) and not tasks:
        add("product_search", {"q": q}, "Products with prices and ratings")
    if not any(t["tool"] in ("finance",) for t in tasks):
        add("web_search", {"q": q}, "Background from the web")
    if re.search(r"\b(best|vs\.?|versus|worth it|should i|recommend|reviews?|experience|opinions?)\b", ql):
        add("forum_search", {"q": q}, "What real users say")
    names = ", ".join(registry.TOOLS[t["tool"]].purpose.split(" (")[0].split(":")[0].lower() for t in tasks)
    return {"intent": "research", "summary": f"I'll look up: {names}.", "tasks": tasks, "rejected": [],
            "assumptions": assumptions, "missing_info": [], "clarifying_question": question, "planned_by": "rules"}


# ------------------------------------------------------------------ execution
def execute(plan: dict, context: dict, query: str) -> tuple[list[dict], list[dict], bool]:
    """Run all tasks in parallel. Returns (observations tagged with task id, call log, demo flag)."""
    def run(task: dict):
        res = registry.run_tool(task["tool"], task["args"], context)
        obs, calls = res["observations"], list(res["calls"])
        task.update(status="done" if obs else ("failed" if not any(c.get("ok") for c in calls) else "empty"),
                    count=len(obs))
        for fb in registry.fallbacks(task["tool"]):     # walk the backup chain until something returns results
            if obs:
                break
            fb_args = {"q": task["args"].get("q") or _clean(query)}
            res2 = registry.run_tool(fb, fb_args, context)
            obs, calls = res2["observations"], calls + res2["calls"]
            task.update(status="fallback" if obs else task["status"], fallback=fb, count=len(obs))
        for o in obs:
            o["task"] = task["id"]
        return obs, calls, bool(res.get("demo"))

    observations, calls, demo = [], [], False
    for obs, c, d in [f.result() for f in [_TASK_POOL.submit(run, t) for t in plan["tasks"]]]:
        observations += obs
        calls += c
        demo = demo or d
    return observations, calls, demo


def evidence_status(o: dict) -> str:
    """How far a value is verified — never upgraded beyond what the source actually returned."""
    a = o.get("attrs") or {}
    if o["kind"] == "hotel" and (o.get("price") or a.get("total_price")):
        return f"price for {a['check_in']} → {a['check_out']}" if a.get("check_in") else "listed price"
    if o["kind"] == "product" and o.get("price"):
        return "listed price"
    if o["kind"] == "quote":
        return f"quote as of {a.get('as_of') or 'search time'}"
    if o["kind"] == "event":
        return "event listing"
    if o["kind"] == "place":
        return "map listing"
    if a.get("ai_generated"):
        return "AI-generated summary (Google)"
    return "search result"


# ------------------------------------------------------------------ evidence + answer
SECTION_TOP = 6

ANSWER_SYSTEM = """You are DecisionOS. Answer the user's request using ONLY the numbered evidence below.
- Lead with the direct answer / recommendation, then the key options or facts, in at most ~220 words.
- Cite every factual claim like [3]. Use the evidence's numbers, prices, dates and ratings exactly.
- Each item has a "status" saying how verified it is (e.g. "listed price", "price for <dates>"); don't claim more
  (a listed price is not confirmed availability).
- If something the user asked for is not in the evidence, say so plainly instead of guessing.
- Mention any assumption listed in the plan. Plain text with short bullet lines, no markdown headings."""


def build_sections(plan: dict, observations: list[dict]) -> tuple[list[dict], list[dict]]:
    sections, evidence = [], []
    for t in plan["tasks"]:
        items = [o for o in observations if o.get("task") == t["id"]]
        items.sort(key=lambda o: (o.get("position") or 99))
        rows = []
        for o in [o for o in items if (o.get("attrs") or {}).get("ai_answer")]:
            # the AI Mode answer itself is evidence for the final answer but not a list item
            evidence.append({"n": len(evidence) + 1, "kind": "ai_answer", "name": o["name"], "url": None,
                             "source": o["source"], "snippet": o["snippet"], "full_text": o["snippet"],
                             "price": None, "currency": None, "rating": None, "reviews": None, "address": None,
                             "thumbnail": None, "attrs": o.get("attrs") or {}, "status": evidence_status(o),
                             "section": t["purpose"]})
        items = [o for o in items if not (o.get("attrs") or {}).get("ai_answer")]
        for o in items[:SECTION_TOP]:
            n = len(evidence) + 1
            row = {"n": n, "kind": o["kind"], "name": o.get("name"), "url": o.get("url"), "source": o.get("source"),
                   "snippet": (o.get("snippet") or "")[:300] or None, "price": o.get("price"),
                   "currency": o.get("currency"), "rating": o.get("rating"), "reviews": o.get("reviews"),
                   "address": o.get("address"), "thumbnail": o.get("thumbnail"),
                   "attrs": {k: v for k, v in (o.get("attrs") or {}).items() if k not in ("data_id",)},
                   "status": evidence_status(o)}
            rows.append(row)
            evidence.append({**row, "section": t["purpose"]})
        sections.append({"task": t["id"], "tool": t["tool"], "title": t["purpose"], "status": t.get("status"),
                         "fallback": t.get("fallback"), "items": rows})
    return sections, evidence


def answer(query: str, plan: dict, evidence: list[dict]) -> dict[str, Any]:
    sources = [{"n": e["n"], "title": e["name"], "url": e["url"], "source": e["source"]} for e in evidence
               if e["kind"] != "ai_answer"]
    if evidence:
        payload = [{k: v for k, v in e.items() if v not in (None, "", {}, []) and k not in ("thumbnail", "url", "full_text")}
                   for e in evidence]
        text = llm.complete_text(ANSWER_SYSTEM, json.dumps(
            {"request": query, "plan": {"summary": plan.get("summary"), "assumptions": plan.get("assumptions")},
             "evidence": payload}, default=str)[:24000], max_tokens=1500)
        if text:
            return {"text": text, "sources": sources, "generated_by": "claude"}
    ai = next((e for e in evidence if e["kind"] == "ai_answer"), None)
    if ai:                                  # no Claude: Google AI Mode's own written answer
        extra = ("\n\nAssumed: " + " ".join(plan["assumptions"])) if plan.get("assumptions") else ""
        return {"text": ai["full_text"] + extra, "sources": sources, "generated_by": "google_ai_mode"}
    return {"text": _fallback_text(plan, evidence), "sources": sources, "generated_by": "template"}


def _line(e: dict) -> str:
    a = e.get("attrs") or {}
    bits = []
    if e.get("price") is not None:
        bits.append(f"{'₹' if (e.get('currency') or 'INR') == 'INR' else (e.get('currency') or '') + ' '}{e['price']:,.0f}"
                    + (" (" + e["status"] + ")" if e["status"] != "search result" else ""))
    elif a.get("total_price"):
        bits.append(f"₹{a['total_price']:,.0f} total ({e['status']})")
    if e.get("rating"):
        bits.append(f"{e['rating']}★" + (f" ({e['reviews']:,})" if isinstance(e.get("reviews"), int) else ""))
    for k in ("when", "venue", "change_pct", "direction", "developer", "location"):
        if a.get(k):
            bits.append(str(a[k]))
    detail = f" — {', '.join(bits)}" if bits else (f" — {e['snippet'][:160]}" if e.get("snippet") else "")
    return f"• {e['name']}{detail} [{e['n']}]"


def _fallback_text(plan: dict, evidence: list[dict]) -> str:
    if not evidence:
        return "None of the searches returned usable results. Try rephrasing with more specific words."
    parts = []
    for title in dict.fromkeys(e["section"] for e in evidence):
        rows = [e for e in evidence if e["section"] == title][:4]
        parts.append(f"{title}:\n" + "\n".join(_line(e) for e in rows))
    if plan.get("assumptions"):
        parts.append("Assumed: " + " ".join(plan["assumptions"]))
    return "\n\n".join(parts)
