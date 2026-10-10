"""Intent Agent: classify a message and extract a structured DecisionSpec.

Claude does the language understanding; a heuristic parser provides a fallback (and keeps
the app usable with no API key). Output is validated/normalised in `normalise_spec`.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .. import llm
from .timeparse import all_clock_times, parse_when

DECISION_TYPES = ["commerce", "local", "errands", "travel", "trip", "knowledge", "video", "image", "general"]

# Default criteria per decision type (weights are re-normalised after merging user priorities).
DEFAULT_CRITERIA: dict[str, list[dict[str, Any]]] = {
    "commerce": [
        {"key": "price", "label": "Price", "weight": 0.35, "direction": "min"},
        {"key": "rating", "label": "Rating", "weight": 0.25, "direction": "max"},
        {"key": "review_confidence", "label": "Review volume", "weight": 0.15, "direction": "max"},
        {"key": "availability", "label": "Delivery speed", "weight": 0.10, "direction": "max"},
    ],
    "image": [
        {"key": "price", "label": "Price", "weight": 0.5, "direction": "min"},
        {"key": "rating", "label": "Rating", "weight": 0.2, "direction": "max"},
        {"key": "review_confidence", "label": "Review volume", "weight": 0.15, "direction": "max"},
        {"key": "availability", "label": "Delivery speed", "weight": 0.15, "direction": "max"},
    ],
    "local": [
        {"key": "rating", "label": "Rating", "weight": 0.35, "direction": "max"},
        {"key": "distance", "label": "Distance", "weight": 0.30, "direction": "min"},
        {"key": "review_confidence", "label": "Review volume", "weight": 0.20, "direction": "max"},
        {"key": "availability", "label": "Open now", "weight": 0.15, "direction": "max"},
    ],
    "travel": [
        {"key": "price", "label": "Cost", "weight": 0.45, "direction": "min"},
        {"key": "duration", "label": "Duration", "weight": 0.40, "direction": "min"},
        {"key": "stops", "label": "Stops / transfers", "weight": 0.15, "direction": "min"},
    ],
    "video": [
        {"key": "relevance", "label": "Relevance", "weight": 0.35, "direction": "max"},
        {"key": "popularity", "label": "Views", "weight": 0.35, "direction": "max"},
        {"key": "recency", "label": "Recency", "weight": 0.30, "direction": "max"},
    ],
    "knowledge": [
        {"key": "j:promise", "label": "Promise of the direction", "weight": 0.4, "direction": "max"},
        {"key": "j:feasibility", "label": "Feasibility for you", "weight": 0.35, "direction": "max"},
        {"key": "j:evidence", "label": "Evidence strength", "weight": 0.25, "direction": "max"},
    ],
    "general": [
        {"key": "relevance", "label": "Relevance", "weight": 1.0, "direction": "max"},
    ],
    "errands": [],
    "trip": [],
}

SPEC_SYSTEM = """You are the Intent Agent of DecisionOS, a decision-and-planning assistant.
Turn the user's request into a structured decision specification.

decision_type is one of:
- commerce: choosing a product to buy
- image: the user supplied an image URL and wants to identify/buy/price the item
- local: choosing a single physical place/service nearby (repair shop, restaurant, clinic)
- errands: several things to do in the physical world, often before a deadline (buy X, print Y, reach Z by T)
- travel: getting from one city to another (compare flight / train / bus / car) — only the journey
- trip: planning a holiday/getaway/multi-day trip (where to go, where to stay, what to do, total cost),
  with or without a fixed destination
- knowledge: research decisions (what topic/problem/direction to pursue), uses papers, patents, news
- video: what to watch to learn something; builds a learning path
- general: anything else (facts, news, events, jobs, apps, stocks, hotels only, restaurants in another city,
  comparisons, opinions...) — a research planner picks the right search tools for it

Return JSON with exactly these keys:
{
 "goal": short goal sentence,
 "decision_type": one of the types above,
 "search_query": the best search query for the main thing to find (product name/category, place type, topic),
 "hard_constraints": {"budget_max": number|null, "currency": "INR" unless stated, "deadline": ISO-8601 local datetime|null,
                      "deadline_text": string|null, "min_rating": number|null, "max_distance_km": number|null,
                      "open_now": bool, "must_include": [strings that MUST appear in the option name]},
 "soft_preferences": [short strings],
 "criteria": [{"key": ..., "label": ..., "weight": 0..1, "direction": "min"|"max"}],
 "subtasks": [{"label": "Print resume", "query": "printing xerox shop", "est_minutes": 15, "est_cost": 40}],
 "destination": {"label": string|null, "query": string|null, "arrive_by": ISO-8601 local datetime|null},
 "travel": {"origin_city": str|null, "dest_city": str|null, "origin_airport": IATA|null, "dest_airport": IATA|null, "date": "YYYY-MM-DD"|null},
 "event": {"title": string|null, "start": ISO-8601|null},
 "trip": {"origin": city|null, "destination": city|null (null when they want suggestions), "days": number|null,
          "start_date": "YYYY-MM-DD"|null, "travellers": number|null, "budget": number|null (total, INR),
          "max_km": number|null, "min_km": number|null, "interests": [str]},
 "needs_plan": bool,
 "clarifying_question": string|null
}

Criteria keys you may use: price, rating, review_confidence, availability, distance, duration, stops,
popularity, recency, relevance, and judgement criteria written as "j:<name>" (e.g. "j:coding_performance",
"j:portability", "j:battery_life", "j:comfort") for qualities that must be judged from product
names/specs. Derive weights from the user's stated priorities; include price when there is a budget.
subtasks/destination only for errands (one subtask per stop; the final place to reach goes in destination).
event is a fixed appointment mentioned (e.g. interview at 10 AM tomorrow).
Only ask a clarifying_question if the request is impossible to act on; otherwise null."""


def _now_str(now: datetime) -> str:
    return now.strftime("%A %Y-%m-%d %H:%M %Z")


# ------------------------------------------------------------------ classification
CLASSIFY_SYSTEM = """Classify the user's message for DecisionOS. Return JSON:
{"intent": "decision" | "reminder" | "remember" | "forget" | "whatif" | "question",
 "task": str|null, "when": ISO-8601 local datetime|null, "memory": str|null}
- reminder: they ask to be reminded / schedule a task ("remind me to...", "add X to my tasks for Friday").
  task = what to do, when = due time.
- remember: they state a durable preference/fact to store ("remember that I prefer buying locally"). memory = the fact.
- forget: they ask to forget something. memory = what to forget.
- whatif: they ask how the current recommendation changes under a different condition.
- question: a factual/general question that isn't a decision.
- decision: anything that needs researching options and recommending one, or planning a goal."""


def classify(message: str, now: datetime, has_active_decision: bool) -> dict[str, Any]:
    out = llm.complete_json(CLASSIFY_SYSTEM, f"Current time: {_now_str(now)}\n"
                                             f"There is an active decision on screen: {has_active_decision}\n"
                                             f"Message: {message}", max_tokens=300)
    if isinstance(out, dict) and out.get("intent"):
        if out.get("when"):
            try:
                out["when"] = _as_local(datetime.fromisoformat(out["when"]), now).isoformat()
            except ValueError:
                out["when"] = None
        if out["intent"] == "reminder" and not out.get("when"):
            w = parse_when(message, now)
            out["when"] = w.isoformat() if w else None
        return out
    return _classify_fallback(message, now, has_active_decision)


def _classify_fallback(message: str, now: datetime, has_active: bool) -> dict[str, Any]:
    m = message.strip()
    ml = m.lower()
    if re.match(r"^(please\s+)?(remind me|set a reminder|add .* to my (tasks|todo|calendar))", ml):
        task = re.sub(r"^(please\s+)?(remind me( to)?|set a reminder( to)?)\s*", "", m, flags=re.I)
        task = re.sub(r"\b(tomorrow|today|tonight|this evening|on \w+day|at \d.*|in \d+ \w+)\b.*$", "", task, flags=re.I).strip(" ,.")
        w = parse_when(m, now)
        return {"intent": "reminder", "task": task or m, "when": w.isoformat() if w else None}
    if re.match(r"^(please\s+)?remember( that)?\b", ml):
        return {"intent": "remember", "memory": re.sub(r"^(please\s+)?remember( that)?\s*", "", m, flags=re.I).strip()}
    if re.match(r"^(please\s+)?forget\b", ml):
        return {"intent": "forget", "memory": re.sub(r"^(please\s+)?forget( that| about)?\s*", "", m, flags=re.I).strip()}
    if has_active and re.match(r"^(what if|what about|and if|if i)\b", ml):
        return {"intent": "whatif"}
    return {"intent": "decision"}


# ------------------------------------------------------------------ spec extraction
def build_spec(query: str, now: datetime, context: dict[str, Any]) -> dict[str, Any]:
    """context: {location_label, memories: [str], image_url}"""
    prompt = (
        f"Current local time: {_now_str(now)}\n"
        f"User's base location: {context.get('location_label') or 'unknown'}\n"
        f"Known user preferences (use as soft preferences if relevant): {context.get('memories') or []}\n"
        f"Image URL supplied: {context.get('image_url') or 'none'}\n\n"
        f"Request: {query}"
    )
    raw = llm.complete_json(SPEC_SYSTEM, prompt, max_tokens=1500)
    spec = raw if isinstance(raw, dict) and raw.get("decision_type") else heuristic_spec(query, now, context)
    spec["extracted_by"] = "claude" if isinstance(raw, dict) and raw.get("decision_type") else "heuristic"
    return normalise_spec(spec, query, now, context)


def _as_local(dt: datetime, now: datetime) -> datetime:
    return dt.replace(tzinfo=now.tzinfo) if dt.tzinfo is None else dt.astimezone(now.tzinfo)


def _iso_or_none(v: Any, now: datetime) -> str | None:
    if not v:
        return None
    try:
        return _as_local(datetime.fromisoformat(str(v)), now).isoformat()
    except ValueError:
        w = parse_when(str(v), now)
        return w.isoformat() if w else None


def normalise_spec(spec: dict[str, Any], query: str, now: datetime, context: dict[str, Any]) -> dict[str, Any]:
    dtype = spec.get("decision_type") if spec.get("decision_type") in DECISION_TYPES else "general"
    if context.get("image_url"):
        dtype = "image"
    spec["decision_type"] = dtype
    spec["goal"] = spec.get("goal") or query
    spec["search_query"] = (spec.get("search_query") or query).strip()
    hc = spec.get("hard_constraints") or {}
    spec["hard_constraints"] = {
        "budget_max": _num(hc.get("budget_max")),
        "currency": hc.get("currency") or "INR",
        "deadline": _iso_or_none(hc.get("deadline"), now),
        "deadline_text": hc.get("deadline_text"),
        "min_rating": _num(hc.get("min_rating")),
        "max_distance_km": _num(hc.get("max_distance_km")),
        "open_now": bool(hc.get("open_now")),
        "must_include": [s for s in (hc.get("must_include") or []) if isinstance(s, str) and s.strip()],
    }
    spec["soft_preferences"] = [s for s in (spec.get("soft_preferences") or []) if isinstance(s, str)]
    spec["criteria"] = merge_criteria(dtype, spec.get("criteria") or [], spec["hard_constraints"]["budget_max"])
    spec["subtasks"] = [
        {"label": s.get("label") or s.get("query"), "query": s.get("query") or s.get("label"),
         "est_minutes": int(_num(s.get("est_minutes")) or 15), "est_cost": _num(s.get("est_cost"))}
        for s in (spec.get("subtasks") or []) if isinstance(s, dict) and (s.get("label") or s.get("query"))
    ]
    dest = spec.get("destination") or {}
    spec["destination"] = {"label": dest.get("label"), "query": dest.get("query") or dest.get("label"),
                           "arrive_by": _iso_or_none(dest.get("arrive_by"), now)}
    ev = spec.get("event") or {}
    spec["event"] = {"title": ev.get("title"), "start": _iso_or_none(ev.get("start"), now)}
    tr = spec.get("travel") or {}
    spec["travel"] = {k: tr.get(k) for k in ("origin_city", "dest_city", "origin_airport", "dest_airport", "date")}
    tp = spec.get("trip") or {}
    spec["trip"] = {"origin": tp.get("origin") or (context.get("location_label") or "").split(",")[0].split("(")[0].strip() or None,
                    "destination": tp.get("destination"), "days": int(_num(tp.get("days")) or 2),
                    "start_date": tp.get("start_date"), "travellers": int(_num(tp.get("travellers")) or 1),
                    "budget": _num(tp.get("budget")) or spec["hard_constraints"]["budget_max"],
                    "max_km": _num(tp.get("max_km")), "min_km": _num(tp.get("min_km")),
                    "interests": [i for i in tp.get("interests") or [] if isinstance(i, str)]}
    spec["needs_plan"] = bool(spec.get("needs_plan", dtype in ("errands", "commerce", "local", "travel", "video")))
    spec["image_url"] = context.get("image_url")
    spec["location"] = context.get("location") or {}
    spec.setdefault("clarifying_question", None)
    return spec


def merge_criteria(dtype: str, given: list[dict], budget: float | None) -> list[dict]:
    valid = []
    for c in given:
        if not isinstance(c, dict) or not c.get("key"):
            continue
        key = str(c["key"]).strip()
        valid.append({"key": key, "label": c.get("label") or key.replace("j:", "").replace("_", " ").title(),
                      "weight": max(0.0, float(_num(c.get("weight")) or 0.1)),
                      "direction": c.get("direction") if c.get("direction") in ("min", "max") else
                      ("min" if key in ("price", "distance", "duration", "stops") else "max")})
    if not valid:
        valid = [dict(c) for c in DEFAULT_CRITERIA.get(dtype, [])]
    elif dtype in ("commerce", "image") and budget and not any(c["key"] == "price" for c in valid):
        valid.append({"key": "price", "label": "Price", "weight": 0.25, "direction": "min"})
    if dtype in ("commerce", "image") and not any(c["key"] == "rating" for c in valid):
        valid.append({"key": "rating", "label": "Rating", "weight": 0.15, "direction": "max"})
    total = sum(c["weight"] for c in valid) or 1.0
    for c in valid:
        c["weight"] = round(c["weight"] / total, 4)
    return valid


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        m = re.search(r"\d[\d,]*\.?\d*", str(v))
        return float(m.group(0).replace(",", "")) if m else None


# ------------------------------------------------------------------ heuristic fallback
AIRPORTS = {"chennai": "MAA", "bangalore": "BLR", "bengaluru": "BLR", "mumbai": "BOM", "delhi": "DEL",
            "new delhi": "DEL", "hyderabad": "HYD", "kolkata": "CCU", "pune": "PNQ", "kochi": "COK",
            "coimbatore": "CJB", "madurai": "IXM", "trichy": "TRZ", "goa": "GOI", "ahmedabad": "AMD",
            "jaipur": "JAI", "lucknow": "LKO", "thiruvananthapuram": "TRV", "trivandrum": "TRV",
            "visakhapatnam": "VTZ", "mangalore": "IXE", "chandigarh": "IXC"}

ERRAND_MAP = [
    (r"\bprint(?:ed|ing)?\b|\bxerox\b|photocop", "Print documents", "printing xerox shop", 15, 50),
    (r"passport (?:size )?photo", "Get passport photos", "passport photo studio", 20, 150),
    (r"\b(?:usb|pen ?drive|flash drive)\b", "Buy USB drive", "computer accessories shop", 15, 450),
    (r"formal shoes?|\bshoes?\b", "Buy shoes", "formal shoe store", 30, 1800),
    (r"\bmedicine|pharmacy|tablets?\b", "Buy medicine", "pharmacy", 10, 200),
    (r"\bgroceries|grocery\b", "Buy groceries", "supermarket", 30, 800),
    (r"\bhaircut|salon\b", "Get a haircut", "salon", 40, 250),
    (r"\bcharger|cable\b", "Buy charger", "mobile accessories shop", 15, 500),
    (r"\bstationery|notebook|pen\b", "Buy stationery", "stationery shop", 10, 150),
    (r"\batm|cash\b", "Withdraw cash", "ATM", 10, 0),
    (r"\b(?:phone|mobile|screen)\b.*\brepair|\brepair.*\b(?:phone|mobile|screen)\b", "Repair phone", "mobile phone repair shop", 45, 1500),
    (r"\bgifts?\b", "Buy a gift", "gift shop", 30, 1000),
    (r"\bbank\b", "Visit the bank", "bank branch", 30, 0),
    (r"\b(?:post office|courier|parcel)\b", "Send a parcel", "courier post office", 15, 100),
]

# Open-ended "where should I go" trips (no fixed destination city) -> web research, not flight search.
TRIP_RE = r"\b(trip|getaway|vacation|holiday|itinerary|tour|road ?trip|places to (?:visit|go)|weekend plan|hill stations?)\b"
RESEARCH_RE = (r"\b(apps?|play store|app store|events?|concerts?|gigs?|meetups?|happening|jobs?|hiring|internships?|"
               r"vacanc\w*|stocks?|share price|nifty|sensex|bitcoin|crypto|trending|trends|search interest|"
               r"pictures? of|photos? of|images? of|news|latest)\b")
RETURN_RE = r"\b(?:be |get |come )?back (?:home|to (?:my )?(?:home|hostel|room))\b|\breach (?:my )?(?:home|hostel)\b"


def _budget(text: str) -> float | None:
    t = text.lower().replace(",", "")
    m = re.search(r"(?:₹|rs\.?|inr)\s*(\d+(?:\.\d+)?)\s*(k|thousand|lakh|l)?\b", t) or \
        re.search(r"(\d+(?:\.\d+)?)\s*(k|thousand|lakh)?\s*(?:rupees|rs|inr)\b", t) or \
        re.search(r"(?:under|below|within|budget(?: is| of)?|less than|max(?:imum)?|i have)\s*(?:₹|rs\.?)?\s*(\d+(?:\.\d+)?)\s*(k|thousand|lakh)?\b", t)
    if not m:
        return None
    v = float(m.group(1))
    mult = (m.group(2) or "").lower()
    return v * (1000 if mult in ("k", "thousand") else 100000 if mult in ("lakh", "l") else 1)


def _detect_type(q: str, context: dict) -> str:
    ql = q.lower()
    if context.get("image_url"):
        return "image"
    errand_hits = sum(1 for pat, *_ in ERRAND_MAP if re.search(pat, ql))
    if errand_hits >= 2 or (errand_hits >= 1 and re.search(r"\breach\b|\bget to\b|" + RETURN_RE, ql)):
        return "errands"
    cities = "|".join(AIRPORTS)
    if re.search(TRIP_RE, ql):
        return "trip"
    if re.search(RESEARCH_RE, ql):          # specialised search tools (apps, events, jobs, markets...) via the planner
        return "general"
    if re.search(rf"\b(?:{cities})\s+to\s+(?:{cities})\b", ql) or re.search(r"\bfrom\s+[a-z ]+\s+to\s+[a-z]+", ql) or re.search(r"\b(?:way|travel|go|get)\s+to\s+(?:" + "|".join(AIRPORTS) + r")\b", ql):
        return "travel"
    if re.search(r"\b(watch|youtube|course|tutorial|learn|learning)\b", ql):
        return "video"
    if re.search(r"\b(research|project (?:about|on)|what problem|paper|thesis|topic|trend)\b", ql):
        return "knowledge"
    if re.search(r"\b(where should i|near me|nearby|repair|service cent|restaurant|cafe|clinic|hospital|salon)\b", ql):
        return "local"
    if re.search(r"\b(buy|purchase|which .* (?:should i )?(?:get|buy)|best .* under|recommend .*(laptop|phone|headphone))\b", ql) \
            or _budget(ql):
        return "commerce"
    return "general"


def _product_query(q: str) -> str:
    s = re.sub(r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\.\d+)?\s*(?:k|thousand|lakh)?", " ", q, flags=re.I)
    s = re.sub(r"\b(under|below|within|budget|less than|i need|i want|need|want|which|what|should|i|buy|get|me|a|an|"
               r"the|best|find|recommend|please|to|is|it|my|for me|this week|today|tomorrow|preferably|and)\b", " ", s, flags=re.I)
    s = re.sub(r"[?.!,]", " ", s)
    return " ".join(s.split()) or q


def _trip_query(ql: str, context: dict) -> str:
    """'suggest a 3 days trip under 600km from chennai, budget 8k' -> 'best places to visit from Chennai for a 3 day trip'.
    Distance/budget numbers stay in the spec; putting them in the search query makes Google results much worse."""
    days = re.search(r"(\d+)\s*-?\s*(?:days?|nights?)", ql)
    origin = re.search(r"\bfrom\s+([a-z]+)", ql)
    origin_name = origin.group(1) if origin else (context.get("location_label") or "").split(",")[0].split("(")[0].strip()
    trip = f"a {days.group(1)} day trip" if days else ("a weekend trip" if "weekend" in ql else "a short trip")
    return f"best places to visit from {origin_name.title()} for {trip}" if origin_name else f"best places to visit for {trip}"


WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "a": 1, "an": 1}


def _trip_fields(q: str, ql: str, context: dict, when: datetime | None) -> dict[str, Any]:
    days = re.search(r"(\d+|one|two|three|four|five|six|seven)\s*-?\s*(days?|nights?)", ql)
    n_days = None
    if days:
        n = int(days.group(1)) if days.group(1).isdigit() else WORD_NUM[days.group(1)]
        n_days = n + 1 if days.group(2).startswith("night") else n
    elif "weekend" in ql:
        n_days = 2
    origin = re.search(r"\bfrom\s+([a-z]+(?:\s[a-z]+)?)", ql)
    origin_name = origin.group(1).split(" and ")[0].split()[0] if origin else None
    dest = re.search(r"\b(?:to|in|visit)\s+([a-z]+)", ql)
    dest_name = dest.group(1) if dest and dest.group(1) not in ("any", "some", "a", "the", "go", "visit", "travel", "plan",
                                                                 "places", "place", "somewhere", "nearby") else None
    kms = [float(k) for k in re.findall(r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilomet)", ql)]
    people = re.search(r"(\d+|two|three|four|five|six)\s*(?:people|persons?|of us|friends|adults)", ql)
    n_people = (int(people.group(1)) if people.group(1).isdigit() else WORD_NUM[people.group(1)]) if people else 1
    if people and "friends" in people.group(0) and "of us" not in ql:
        n_people += 1                                   # "with 3 friends" = 4 travellers
    min_km = kms[0] if len(kms) >= 2 and re.search(r"\b(at least|more than|minimum|over|beyond)\b", ql) else None
    start = None
    if re.search(r"\bweekend\b", ql) and when:
        sat = when.date() - timedelta(days=(when.weekday() - 5) % 7)      # the Saturday of that weekend
        start = sat.isoformat()
    elif when and re.search(r"\b(today|tomorrow|next week|(?:on|next|this|coming) \w+day|\d{1,2}(?:st|nd|rd|th)\b|jan|feb|mar|apr|may|jun|"
                            r"jul|aug|sep|oct|nov|dec|\d{4}-\d{2}-\d{2})", ql):
        start = when.date().isoformat()
    return {"origin": (origin_name or "").title() or None, "destination": dest_name.title() if dest_name else None,
            "days": n_days or 2, "start_date": start, "travellers": n_people,
            "budget": _budget(q), "max_km": max(kms) if kms else None, "min_km": min_km,
            "interests": [w for w in ("beach", "hills", "temple", "trek", "food", "nature", "wildlife", "heritage")
                          if w in ql]}


def heuristic_spec(q: str, now: datetime, context: dict) -> dict[str, Any]:
    dtype = _detect_type(q, context)
    ql = q.lower()
    deadline = parse_when(q, now)
    spec: dict[str, Any] = {
        "goal": q, "decision_type": dtype, "search_query": _product_query(q),
        "hard_constraints": {"budget_max": _budget(q), "deadline": deadline.isoformat() if deadline else None,
                             "deadline_text": None, "open_now": dtype == "local" and "now" in ql},
        "soft_preferences": [p for p in ("lightweight", "battery", "cheap", "comfortable", "durable", "local")
                             if p in ql],
        "criteria": [],
    }
    if dtype == "commerce":
        soft = {"j:portability": r"lightweight|light weight|portable|thin",
                "j:battery_life": r"battery",
                "j:performance": r"coding|programming|gaming|editing|performance|fast",
                "j:comfort": r"comfortable|comfort"}
        extra = [{"key": k, "label": k[2:].replace("_", " ").title(), "weight": 0.2, "direction": "max"}
                 for k, pat in soft.items() if re.search(pat, ql)]
        if extra:
            spec["criteria"] = [dict(c) for c in DEFAULT_CRITERIA["commerce"]] + extra
    if dtype == "trip":
        spec["search_query"] = _trip_query(ql, context)
        spec["trip"] = _trip_fields(q, ql, context, deadline)
    if dtype == "local":
        spec["search_query"] = " ".join(re.sub(r"\b(where should i|where can i|near me|nearby|go to|my)\b", " ", ql).strip(" ?").split()) or q
    if dtype == "errands":
        subtasks = []
        for pat, label, query, mins, cost in ERRAND_MAP:
            if re.search(pat, ql):
                subtasks.append({"label": label, "query": query, "est_minutes": mins, "est_cost": cost})
        spec["subtasks"] = subtasks
        m = re.search(r"\breach\s+(?:the\s+|my\s+)?([a-z ]+?)(?:\s+by|\s+before|\s+at|[,.]|$)", ql)
        times = all_clock_times(q)
        arrive = None
        for h, mi, before in times:
            if "reach" in before or "by" in before[-6:]:
                base = parse_when(q, now) or now
                arrive = base.replace(hour=h, minute=mi)
        if arrive is None and times:
            h, mi, _ = times[-1]
            arrive = (deadline or now).replace(hour=h, minute=mi)
        dest_label = m.group(1).strip() if m else ("home" if re.search(RETURN_RE, ql) else None)
        spec["destination"] = {"label": dest_label.title() if dest_label else None, "query": dest_label,
                               "arrive_by": arrive.isoformat() if arrive else None}
        ev = re.search(r"\b(interview|exam|meeting|presentation|appointment)\b", ql)
        if ev:
            spec["event"] = {"title": ev.group(1).title(), "start": None}
            for h, mi, before in times:
                if ev.group(1) in before:
                    spec["event"]["start"] = (parse_when(q, now) or now).replace(hour=h, minute=mi).isoformat()
    if dtype == "travel":
        cities = "|".join(AIRPORTS)
        m = re.search(r"from\s+([a-z ]+?)\s+to\s+([a-z]+)", ql) or re.search(rf"\b({cities})\s+to\s+({cities})\b", ql)
        origin, dest = (m.group(1).strip(), m.group(2).strip()) if m else (None, None)
        if not dest:
            m2 = re.search(r"to\s+(" + "|".join(AIRPORTS) + r")\b", ql)
            dest = m2.group(1) if m2 else None
        spec["travel"] = {"origin_city": origin.title() if origin else context.get("location_label"),
                          "dest_city": dest.title() if dest else None,
                          "origin_airport": AIRPORTS.get(origin or ""), "dest_airport": AIRPORTS.get(dest or ""),
                          "date": deadline.date().isoformat() if deadline else None}
    if dtype == "video":
        topic = re.sub(r"\b(i'?m|i am|trying to|i want to|learn|learning|what should i watch|watch|about|on youtube)\b", " ", ql)
        spec["search_query"] = " ".join(re.sub(r"[?.!,]", " ", topic).split()) or q
    return spec
