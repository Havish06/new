"""Semantic capability tools (the "Universal Decision Router").

The orchestrator never sees SerpApi engine names. It asks for a capability such as
`research_product` and this module fans out to the right engines, then normalises every
result into a common *observation* record:

    {kind, name, source, engine, url, id, price, currency, rating, reviews,
     lat, lng, address, hours, open_state, attrs, snippet, thumbnail, position}

Adding another API later only means adding an engine call + parser here.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Callable

from ..config import settings
from . import client

log = logging.getLogger("decisionos.capabilities")

_POOL = ThreadPoolExecutor(max_workers=8)


# ---------------------------------------------------------------- helpers
def parse_price(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return parse_price(v.get("extracted") or v.get("extracted_value") or v.get("value") or v.get("raw"))
    m = re.search(r"(\d[\d,]*\.?\d*)", str(v))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_price_range(v: Any) -> tuple[float, float] | None:
    """'₹100–200' / '₹1,000-3,000' -> (100, 200)."""
    if not v:
        return None
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", str(v))]
    if not nums:
        return None
    return (nums[0], nums[-1])


def _obs(**kw: Any) -> dict[str, Any]:
    base = {"kind": None, "name": None, "source": None, "engine": None, "url": None, "id": None,
            "price": None, "currency": settings.currency, "rating": None, "reviews": None,
            "lat": None, "lng": None, "address": None, "hours": None, "open_state": None,
            "attrs": {}, "snippet": None, "thumbnail": None, "position": None}
    base.update({k: v for k, v in kw.items() if v is not None})
    return base


def _run(calls: list[tuple[str, dict, Callable[[dict], list[dict]]]]) -> tuple[list[dict], list[dict], bool]:
    """Execute engine calls concurrently. Returns (observations, call_log, demo_flag)."""
    def one(engine: str, params: dict, parser: Callable[[dict], list[dict]]):
        try:
            data = client.search(engine, params)
            extra_calls = 0
            token = (data.get("ai_overview") or {}).get("page_token")
            if engine == "google" and params.get("__overview") and token:
                # Google returns some AI Overviews only via a follow-up call; the token expires in ~1 min,
                # so a stale token from a cached search just fails quietly.
                try:
                    ov = client.search("google_ai_overview", {"page_token": token})
                    if (ov.get("ai_overview") or {}).get("text_blocks"):
                        data = {**data, "ai_overview": ov["ai_overview"]}
                    extra_calls = 1
                except Exception as exc:
                    log.info("AI overview follow-up failed: %s", exc)
            obs = parser(data)
            meta = data.get("search_metadata", {})
            return obs, {"engine": engine + (" + google_ai_overview" if extra_calls else ""),
                         "params": {k: v for k, v in params.items() if not k.startswith("__")},
                         "ok": True, "count": len(obs), "cached": bool(meta.get("cached")),
                         "error": data.get("error") if not obs else None}, bool(meta.get("demo"))
        except Exception as exc:
            log.warning("engine %s failed: %s", engine, exc)
            return [], {"engine": engine, "params": {k: v for k, v in params.items() if not k.startswith("__")},
                        "ok": False, "count": 0, "error": str(exc)[:200]}, False

    futures = [_POOL.submit(one, e, p, f) for e, p, f in calls]
    observations, log_rows, demo = [], [], False
    for fut in futures:
        obs, row, is_demo = fut.result()
        observations.extend(obs)
        log_rows.append(row)
        demo = demo or is_demo
    return observations, log_rows, demo


def _result(capability: str, calls: list, extra: dict | None = None) -> dict[str, Any]:
    obs, call_log, demo = _run(calls)
    out = {"capability": capability, "observations": obs, "calls": call_log, "demo": demo}
    out.update(extra or {})
    return out


# ---------------------------------------------------------------- parsers
def _p_google(data: dict) -> list[dict]:
    out = [_obs(kind="article", name=r.get("title"), source=r.get("source") or "Google Search", engine="google",
                url=r.get("link"), snippet=r.get("snippet"), position=r.get("position"))
           for r in data.get("organic_results", [])]
    for f in data.get("discussions_and_forums", []) or []:
        answers = " ".join(a.get("snippet", "") for a in f.get("answers", []) or [])
        out.append(_obs(kind="article", name=f.get("title"), source=f.get("source") or "Forum", engine="google",
                        url=f.get("link"), snippet=answers or f.get("snippet"), attrs={"forum": True}))
    if data.get("answer_box"):
        ab = data["answer_box"]
        out.insert(0, _obs(kind="article", name=ab.get("title") or "Answer box", source="Google answer box",
                           engine="google", url=ab.get("link"), snippet=ab.get("answer") or ab.get("snippet")))
    return _p_ai_overview(data.get("ai_overview") or {}) + _p_google_blocks(data) + out


def _p_google_blocks(data: dict) -> list[dict]:
    """Structured blocks Google already returns with a normal search: knowledge graph, sports scores,
    top stories, top sights, popular destinations, related questions."""
    out = []
    kg = data.get("knowledge_graph") or {}
    if kg.get("title"):
        facts = {k: v for k, v in kg.items() if isinstance(v, str) and k not in
                 ("title", "type", "description", "kgmid", "knowledge_graph_search_link", "serpapi_knowledge_graph_search_link",
                  "website", "header_images") and len(v) < 120}
        out.append(_obs(kind="article", name=kg["title"] + (f" — {kg['type']}" if kg.get("type") else ""),
                        source="Google Knowledge Graph", engine="google", url=kg.get("website") or (kg.get("source") or {}).get("link"),
                        snippet=kg.get("description"), position=0, attrs={"facts": dict(list(facts.items())[:8]), "kg": True}))
    sp = data.get("sports_results") or {}
    if sp.get("title"):
        g = sp.get("game_spotlight") or {}
        def score(t):
            sc = t.get("score")
            return sc.get("total") if isinstance(sc, dict) else sc
        teams = " vs ".join(f"{t.get('name')} {score(t) if score(t) is not None else ''}".strip() for t in g.get("teams") or [])
        games = [" vs ".join(f"{t.get('name')} {t.get('score') or ''}".strip() for t in x.get("teams") or [])
                 + f" ({x.get('status') or x.get('date') or ''})" for x in (sp.get("games") or [])[:4]]
        out.append(_obs(kind="score", name=sp["title"], source="Google Sports", engine="google", position=0,
                        snippet=" · ".join(filter(None, [teams, g.get("status"), g.get("date"), g.get("league") if isinstance(g.get("league"), str) else None]))
                                or "; ".join(games), attrs={"games": games, "when": g.get("date")}))
    ts = data.get("top_stories") or []
    items = ts if isinstance(ts, list) else [i for grp in ts.values() if isinstance(grp, list) for i in grp]
    for i, r in enumerate(items[:6]):
        out.append(_obs(kind="article", name=r.get("title"), source=r.get("source") or "Top stories", engine="google",
                        url=r.get("link"), thumbnail=r.get("thumbnail"), position=i + 1,
                        attrs={"date": r.get("date"), "top_story": True, **({"live": True} if r.get("live") else {})}))
    for i, r in enumerate(((data.get("top_sights") or {}).get("sights") or [])[:8]):
        out.append(_obs(kind="attraction", name=r.get("title"), source="Google Top Sights", engine="google",
                        url=r.get("link"), snippet=r.get("description"), rating=r.get("rating"), reviews=r.get("reviews"),
                        thumbnail=r.get("thumbnail"), position=i + 1))
    for i, r in enumerate(((data.get("popular_destinations") or {}).get("destinations") or [])[:10]):
        out.append(_obs(kind="destination", name=r.get("title"), source="Google Travel", engine="google", url=r.get("link"),
                        snippet=r.get("description"), thumbnail=r.get("thumbnail"), position=i + 1,
                        attrs={k: v for k, v in {"flight_price": r.get("extracted_flight_price"),
                                                 "hotel_price": r.get("extracted_hotel_price"),
                                                 "flight_duration": r.get("flight_duration"),
                                                 "drive_duration": r.get("drive_duration")}.items() if v}))
    for r in (data.get("related_questions") or [])[:4]:
        if r.get("question") and r.get("snippet"):
            out.append(_obs(kind="article", name=r["question"], source=r.get("source") or "People also ask", engine="google",
                            url=r.get("link"), snippet=r.get("snippet"), position=20, attrs={"faq": True}))
    return out


def _p_ai_overview(ao: dict) -> list[dict]:
    """Google's AI Overview: a summary paragraph + list items (e.g. one per destination/product/option).
    Marked ai_generated so answers never present it as a verified fact."""
    paras, items = [], []
    refs = {r.get("index"): r for r in ao.get("references") or []}

    def walk(blocks: list) -> None:
        for b in blocks or []:
            if b.get("type") == "paragraph" and b.get("snippet"):
                paras.append(b["snippet"])
            for it in b.get("list") or []:
                title = re.sub(r"\s*[:\-–]\s*$", "", (it.get("title") or "").strip())
                detail = it.get("snippet") or " ".join(x.get("snippet", "") for x in it.get("list") or [])
                m = re.match(r"([^:]{2,60}):\s+(.+)", detail or "", re.S) if not title else None
                if m:                                    # items often come as "Name: description"
                    title, detail = m.group(1).strip(), m.group(2).strip()
                ref = refs.get((it.get("reference_indexes") or [None])[0]) or {}
                if title or detail:
                    items.append(_obs(kind="article", name=title or detail[:80], source="Google AI Overview",
                                      engine="google_ai_overview", url=it.get("link") or ref.get("link"),
                                      snippet=detail if title else None, position=0,
                                      attrs={"ai_generated": True, "overview_item": True}))
            if b.get("type") == "expandable":
                walk(b.get("text_blocks") or [])
    walk(ao.get("text_blocks") or [])
    head = []
    if paras:
        head.append(_obs(kind="article", name="Google AI Overview", source="Google AI Overview",
                         engine="google_ai_overview", snippet=" ".join(paras)[:700], position=0,
                         attrs={"ai_generated": True}))
    return head + items


def _p_shopping(data: dict) -> list[dict]:
    out = []
    for r in data.get("shopping_results", []) + data.get("inline_shopping_results", []):
        attrs = {"delivery": r.get("delivery"), "merchant": r.get("source")}
        if r.get("extensions"):
            attrs["extensions"] = r["extensions"]
        out.append(_obs(kind="product", name=r.get("title"), source=f"Google Shopping · {r.get('source') or 'merchant'}",
                        engine="google_shopping", url=r.get("product_link") or r.get("link"),
                        id=r.get("product_id"), price=parse_price(r.get("extracted_price") or r.get("price")),
                        rating=r.get("rating"), reviews=r.get("reviews"), thumbnail=r.get("thumbnail"),
                        position=r.get("position"), attrs={k: v for k, v in attrs.items() if v}))
    return out


def _p_amazon(data: dict) -> list[dict]:
    out = []
    for r in data.get("organic_results", []):
        delivery = r.get("delivery")
        if isinstance(delivery, list):
            delivery = "; ".join(map(str, delivery))
        out.append(_obs(kind="product", name=r.get("title"), source="Amazon", engine="amazon", url=r.get("link"),
                        id=r.get("asin"), price=parse_price(r.get("extracted_price") or r.get("price")),
                        rating=r.get("rating"), reviews=r.get("reviews"), thumbnail=r.get("thumbnail"),
                        position=r.get("position"), attrs={"delivery": delivery} if delivery else {}))
    return out


def _p_ebay(data: dict) -> list[dict]:
    out = []
    for r in data.get("organic_results", []):
        out.append(_obs(kind="product", name=r.get("title"), source="eBay", engine="ebay", url=r.get("link"),
                        price=parse_price(r.get("price")), currency="USD", rating=r.get("rating"),
                        reviews=r.get("reviews"), attrs={"condition": r.get("condition")}, position=r.get("position")))
    return out


def _p_walmart(data: dict) -> list[dict]:
    out = []
    for r in data.get("organic_results", []):
        offer = r.get("primary_offer") or {}
        out.append(_obs(kind="product", name=r.get("title"), source="Walmart", engine="walmart",
                        url=r.get("product_page_url"), price=parse_price(offer.get("offer_price")), currency="USD",
                        rating=r.get("rating"), reviews=r.get("reviews"), position=r.get("position")))
    return out


def _p_maps(data: dict) -> list[dict]:
    rows = data.get("local_results") or ([data["place_results"]] if data.get("place_results") else [])
    out = []
    for r in rows:
        gps = r.get("gps_coordinates") or {}
        out.append(_obs(kind="place", name=r.get("title"), source="Google Maps", engine="google_maps",
                        url=r.get("website") or (f"https://www.google.com/maps/place/?q=place_id:{r['place_id']}"
                                                  if r.get("place_id") else None),
                        id=r.get("place_id") or r.get("data_id"), rating=r.get("rating"), reviews=r.get("reviews"),
                        lat=gps.get("latitude"), lng=gps.get("longitude"), address=r.get("address"),
                        hours=r.get("operating_hours"), open_state=r.get("open_state") or r.get("hours"),
                        thumbnail=r.get("thumbnail"), position=r.get("position"),
                        attrs={k: v for k, v in {"price_level": r.get("price"), "type": r.get("type"),
                                                 "phone": r.get("phone"), "data_id": r.get("data_id")}.items() if v}))
    return out


def _p_news(data: dict) -> list[dict]:
    out = []
    for r in data.get("news_results", []):
        src = r.get("source")
        out.append(_obs(kind="article", name=r.get("title"), source=(src or {}).get("name") if isinstance(src, dict) else src,
                        engine="google_news", url=r.get("link"), snippet=r.get("snippet"),
                        attrs={"date": r.get("date")}, position=r.get("position")))
    return out


def _p_scholar(engine: str):
    def parse(data: dict) -> list[dict]:
        out = []
        for r in data.get("organic_results", []):
            cited = ((r.get("inline_links") or {}).get("cited_by") or {}).get("total")
            out.append(_obs(kind="paper", name=r.get("title"), source="Google Scholar" if engine == "google_scholar" else "Google Patents",
                            engine=engine, url=r.get("link") or r.get("patent_link"), snippet=r.get("snippet"),
                            attrs={"cited_by": cited, "publication": (r.get("publication_info") or {}).get("summary"),
                                   "date": r.get("publication_date") or r.get("filing_date")},
                            position=r.get("position")))
        return out
    return parse


def _length_to_min(length: Any) -> float | None:
    if not length:
        return None
    parts = [int(p) for p in str(length).split(":") if p.isdigit()]
    if not parts:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return round(secs / 60, 1)


def _p_youtube(data: dict) -> list[dict]:
    out = []
    for r in data.get("video_results", []):
        ch = r.get("channel") or {}
        out.append(_obs(kind="video", name=r.get("title"), source=f"YouTube · {ch.get('name', '')}".strip(" ·"),
                        engine="youtube", url=r.get("link"), snippet=r.get("description"),
                        thumbnail=(r.get("thumbnail") or {}).get("static") if isinstance(r.get("thumbnail"), dict) else r.get("thumbnail"),
                        attrs={"channel": ch.get("name"), "views": r.get("views"), "length_min": _length_to_min(r.get("length")),
                               "published": r.get("published_date"), "verified": ch.get("verified")},
                        position=r.get("position_on_page")))
    return out


def _p_lens(data: dict) -> list[dict]:
    out = []
    for r in data.get("visual_matches", []):
        out.append(_obs(kind="product", name=r.get("title"), source=f"Google Lens · {r.get('source', 'web')}",
                        engine="google_lens", url=r.get("link"), price=parse_price(r.get("price")),
                        thumbnail=r.get("thumbnail"), position=r.get("position"), attrs={"merchant": r.get("source")}))
    return out


def _p_flights(data: dict) -> list[dict]:
    out = []
    for bucket in ("best_flights", "other_flights"):
        for r in data.get(bucket, []) or []:
            legs = r.get("flights") or []
            if not legs:
                continue
            first, last = legs[0], legs[-1]
            name = " + ".join(dict.fromkeys(l.get("airline", "") for l in legs)) + f" {first.get('flight_number', '')}"
            out.append(_obs(kind="flight", name=name.strip(), source="Google Flights", engine="google_flights",
                            price=parse_price(r.get("price")),
                            attrs={"mode": "flight", "depart": (first.get("departure_airport") or {}).get("time"),
                                   "arrive": (last.get("arrival_airport") or {}).get("time"),
                                   "duration_min": r.get("total_duration"), "stops": len(legs) - 1,
                                   "best": bucket == "best_flights"}))
    return out


def _p_hotels(data: dict) -> list[dict]:
    out = []
    for i, r in enumerate(data.get("properties", []) or []):
        gps = r.get("gps_coordinates") or {}
        out.append(_obs(kind="hotel", name=r.get("name"), source="Google Hotels", engine="google_hotels", url=r.get("link"),
                        price=parse_price((r.get("rate_per_night") or {}).get("extracted_lowest")),
                        rating=r.get("overall_rating"), reviews=r.get("reviews"),
                        lat=gps.get("latitude"), lng=gps.get("longitude"), position=i + 1,
                        thumbnail=((r.get("images") or [{}])[0] or {}).get("thumbnail"),
                        attrs={k: v for k, v in {
                            "type": r.get("type"),
                            "total_price": parse_price((r.get("total_rate") or {}).get("extracted_lowest")),
                            "amenities": (r.get("amenities") or [])[:6],
                            "nearby": [n.get("name") for n in (r.get("nearby_places") or [])[:3] if n.get("name")],
                            "check_in": data.get("search_parameters", {}).get("check_in_date"),
                            "check_out": data.get("search_parameters", {}).get("check_out_date"),
                            "property_token": r.get("property_token"),
                        }.items() if v}))
    return out


def _p_airbnb(data: dict) -> list[dict]:
    out = []
    for r in data.get("organic_results", []) or []:
        gps = r.get("gps_coordinates") or {}
        out.append(_obs(kind="hotel", name=r.get("title") or r.get("name"), source="Airbnb", engine="airbnb",
                        url=r.get("link"), rating=r.get("rating"), reviews=r.get("reviews"),
                        lat=gps.get("latitude"), lng=gps.get("longitude"), position=r.get("position"),
                        thumbnail=r.get("thumbnail"),
                        # Airbnb's price is the total for the stay (price_qualifier says e.g. "for 2 nights")
                        attrs={k: v for k, v in {"total_price": parse_price(r.get("extracted_price") or r.get("price")),
                                                 "price_note": r.get("price_qualifier"),
                                                 "check_in": r.get("check_in_date"),
                                                 "check_out": r.get("check_out_date"),
                                                 "type": "Vacation rental"}.items() if v}))
    return out


def _p_tripadvisor(data: dict) -> list[dict]:
    kinds = {"ATTRACTION": "attraction", "RESTAURANT": "place", "ACCOMMODATION": "hotel", "GEO": "destination"}
    return [_obs(kind=kinds.get(str(r.get("place_type") or "").upper(), "attraction"), name=r.get("title"),
                 source="Tripadvisor", engine="tripadvisor", url=r.get("link"), id=r.get("place_id"),
                 snippet=r.get("description"), address=r.get("location"), thumbnail=r.get("thumbnail"),
                 position=r.get("position"), attrs={"place_type": r.get("place_type")})
            for r in data.get("places", []) or []]


def ai_mode_text(data: dict) -> str:
    """Plain-text answer from a google_ai_mode response (markdown stripped to readable text)."""
    md = data.get("reconstructed_markdown") or "\n\n".join(
        b.get("snippet", "") for b in data.get("text_blocks") or [] if b.get("snippet"))
    md = re.sub(r"\\([\\`*_{}\[\]()#+\-.!~>|=])", r"\1", md or "")   # markdown escapes: "3\-day" -> "3-day"
    md = re.sub(r"\$[^$\n]*\$\s*", "", md)                       # LaTeX like $\mathbf{\$15}$ (USD duplicates)
    md = re.sub(r"\*\*|__|`", "", md)
    md = re.sub(r"\s*\[\d+\](?:\s*\[\d+\])*", "", md)                 # AI Mode's own [0]-style citation markers
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.M)
    md = re.sub(r"\[(\d+)\]\([^)]*\)", r"[\1]", md)          # [1](link) -> [1]
    md = re.sub(r"\[([^\]]+)\]\((?:https?:)?[^)]*\)", r"\1", md)  # [text](link) -> text
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def _hours(text: str) -> float | None:
    """'~4 hours 10 minutes' -> 4.17, '5.5 to 7 hours' -> 7, '10–11 hours' -> 11."""
    rng = re.search(r"(\d+(?:\.\d+)?)\s*(?:[–-]|to)\s*(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", text)
    hm = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b(?:\s*(?:and\s*)?(\d+)\s*(?:minutes?|mins?|m)\b)?", text)
    if hm and (not rng or hm.start() < rng.start()):
        return round(float(hm.group(1)) + (int(hm.group(2)) / 60 if hm.group(2) else 0), 2)
    if rng:
        return float(rng.group(2))
    return None


MODE_WORDS = r"train|bus|cab|car|taxi|flight|drive|driving|volvo|sleeper|express|shatabdi|vande"


def parse_transport_options(text: str) -> list[dict]:
    """Top-level bullets about a way to travel ('- By Direct Bus (Cheapest): ... Cost: ₹800–₹1,500') -> options.
    Costs are per person one way unless it's a cab/car (per vehicle)."""
    opts = []
    for b in re.split(r"\n(?=[-*•]\s)", "\n" + text)[1:]:
        head = b.split("\n")[0].lstrip("-*• ").strip()
        m = re.match(r"(?:By\s+)?([^:(\n]{2,60}?)\s*(?:\(([^)]*)\))?\s*(?::|$)", head)
        if not m or not re.search(MODE_WORDS, m.group(1), re.I):
            continue
        body = b.split("\n\n")[0]
        lows, highs = [], []
        cost_lines = [l for l in body.split("\n") if re.search(r"cost|fare|price|ticket|₹", l, re.I)]
        for lo, hi in re.findall(r"₹\s*([\d,]+)(?:\s*(?:[–-]|to)\s*₹?\s*([\d,]+))?", cost_lines[0] if cost_lines else ""):
            lows.append(float(lo.replace(",", "")))
            highs.append(float((hi or lo).replace(",", "")))
        mode = m.group(1).strip()
        opts.append({"mode": mode, "label": mode + (f" ({m.group(2)})" if m.group(2) else ""),
                     "cost_low": sum(lows) if lows else None, "cost_high": sum(highs) if highs else None,
                     "per_vehicle": bool(re.search(r"\bcab|taxi|car\b|drive|driving", mode, re.I))
                                    and not re.search(r"bus|train", mode, re.I),
                     "hours": _hours(body),
                     "detail": " ".join(l.strip(" -*•") for l in body.split("\n")[1:] if l.strip())[:300]
                               or head[m.end():].strip()[:300]})
    return opts


def parse_itinerary(text: str) -> list[dict]:
    """'Day 1: Title' followed by bullet lines -> [{day, title, items}]."""
    days = []
    for m in re.finditer(r"(?:^|\n)\s*Day\s*(\d+)\s*[:\-–]?\s*([^\n]*)\n(.*?)(?=\n\s*Day\s*\d+\s*[:\-–]|\Z)", text, re.S):
        items, blank = [], False
        for l in m.group(3).split("\n"):
            if not l.strip():
                blank = True
                continue
            if not re.match(r"\s*[-*•]\s+\S", l):
                if blank and items:
                    break                     # a new non-list section (e.g. "Budget breakdown") ends the day
                continue
            if blank and items and not re.match(r"\s{2,}", l) and re.match(r"\s*[-*•]\s+(Travel|Accommodation|Food|Total|Local|Budget)", l):
                break
            items.append(re.sub(r"\s+", " ", l.strip(" -*•")).strip())
            blank = False
        if items:
            days.append({"day": int(m.group(1)), "title": m.group(2).strip() or f"Day {m.group(1)}", "items": items[:8]})
    return days


def _p_ai_mode(data: dict) -> list[dict]:
    text = ai_mode_text(data)
    out = []
    if text:
        out.append(_obs(kind="article", name="Google AI Mode answer", source="Google AI Mode", engine="google_ai_mode",
                        snippet=text, position=0, attrs={"ai_generated": True, "ai_answer": True}))
    for r in data.get("references") or []:
        out.append(_obs(kind="article", name=r.get("title"), source=r.get("source") or "Google AI Mode source",
                        engine="google_ai_mode", url=r.get("link"), snippet=r.get("snippet"),
                        position=(r.get("index") or 0) + 1, attrs={"ai_reference": True}))
    for r in data.get("shopping_results") or []:
        out.append(_obs(kind="product", name=r.get("title"), source="Google AI Mode · Shopping", engine="google_ai_mode",
                        url=r.get("product_link"), price=parse_price(r.get("extracted_price") or r.get("price")),
                        thumbnail=r.get("thumbnail"), position=(r.get("index") or 0) + 1))
    return out


def _p_travel_explore(data: dict) -> list[dict]:
    out = []
    for i, r in enumerate(data.get("destinations") or []):
        gps = r.get("gps_coordinates") or {}
        out.append(_obs(kind="destination", name=r.get("name"), source="Google Travel Explore", engine="google_travel_explore",
                        price=parse_price(r.get("flight_price")), lat=gps.get("latitude"), lng=gps.get("longitude"),
                        thumbnail=r.get("thumbnail"), position=i + 1,
                        attrs={k: v for k, v in {"country": r.get("country"), "airport": (r.get("destination_airport") or {}).get("code"),
                                                 "flight_minutes": r.get("flight_duration"), "stops": r.get("number_of_stops"),
                                                 "airline": r.get("airline"), "date": r.get("start_date")}.items() if v is not None}))
    return out


def _p_maps_reviews(data: dict) -> list[dict]:
    info = data.get("place_info") or {}
    topics = [f"{t.get('keyword')} ({t.get('mentions')})" for t in (data.get("topics") or [])[:6] if t.get("keyword")]
    out = []
    for i, r in enumerate((data.get("reviews") or [])[:8]):
        text = ((r.get("extracted_snippet") or {}).get("original") if isinstance(r.get("extracted_snippet"), dict) else None) or r.get("snippet")
        if not text:
            continue
        out.append(_obs(kind="review", name=f"{(r.get('user') or {}).get('name') or 'Reviewer'} on {info.get('title') or 'this place'}",
                        source="Google Maps reviews", engine="google_maps_reviews", url=r.get("link"), rating=r.get("rating"),
                        snippet=text[:400], position=i + 1,
                        attrs={k: v for k, v in {"date": r.get("date"), "topics": topics if i == 0 else None,
                                                 "local_guide": (r.get("user") or {}).get("local_guide")}.items() if v}))
    return out


def _p_hotel_reviews(data: dict) -> list[dict]:
    return [_obs(kind="review", name=f"{(r.get('user') or {}).get('name') or 'Guest'} ({r.get('source') or 'Google'})",
                 source="Google Hotels reviews", engine="google_hotels_reviews", rating=r.get("rating"),
                 snippet=(r.get("snippet") or "")[:400], position=i + 1,
                 attrs={k: v for k, v in {"date": r.get("date"), "subratings": r.get("subratings"),
                                          "best_rating": r.get("best_rating")}.items() if v})
            for i, r in enumerate((data.get("reviews") or [])[:6]) if r.get("snippet")]


def _p_markets(data: dict) -> list[dict]:
    out = []
    home = {"in": "india", "jp": "asia", "sg": "asia", "gb": "europe", "uk": "europe", "de": "europe", "fr": "europe"}.get(
        settings.country.lower(), "us")
    markets = data.get("markets") or {}
    for region in sorted(markets, key=lambda r: (r != home and not (home == "india" and r == "asia"), r == "futures")):   # the user's own region first
        rows = markets[region]
        for r in (rows or [])[:6]:
            mv = r.get("price_movement") or {}
            out.append(_obs(kind="quote", name=f"{r.get('name')} ({region})", source="Google Finance Markets",
                            engine="google_finance_markets", url=r.get("link"), price=parse_price(r.get("price")),
                            position=len(out) + 1,
                            attrs={k: v for k, v in {"movement": mv.get("movement"), "change_pct": mv.get("percentage"),
                                                     "change": mv.get("value"), "region": region,
                                                     "as_of": "market snapshot"}.items() if v is not None}))
    return out


def _p_trending_now(data: dict) -> list[dict]:
    return [_obs(kind="trend", name=r.get("query"), source="Google Trends · Trending now", engine="google_trends_trending_now",
                 position=i + 1, snippet=", ".join((r.get("trend_breakdown") or [])[:5]) or None,
                 attrs={k: v for k, v in {"search_volume": r.get("search_volume"), "increase_pct": r.get("increase_percentage"),
                                          "categories": [c.get("name") for c in r.get("categories") or []],
                                          "direction": "active" if r.get("active") else "cooling"}.items() if v})
            for i, r in enumerate((data.get("trending_searches") or [])[:15])]


def _p_simple_organic(source: str, engine: str):
    def parse(data: dict) -> list[dict]:
        return [_obs(kind="article", name=r.get("title"), source=r.get("source") or r.get("displayed_link") or source,
                     engine=engine, url=r.get("link"), snippet=r.get("snippet"), position=r.get("position") or i + 1,
                     attrs={"date": r.get("date")} if r.get("date") else {})
                for i, r in enumerate(data.get("organic_results") or [])]
    return parse


def _p_bing_copilot(data: dict) -> list[dict]:
    parts = [data.get("header") or ""]
    for b in data.get("text_blocks") or []:
        if b.get("snippet"):
            parts.append(b["snippet"])
        for it in b.get("list") or []:
            parts.append("- " + (it.get("snippet") or it.get("title") or ""))
    text = "\n\n".join(p for p in parts if p).strip()
    out = [_obs(kind="article", name="Bing Copilot answer", source="Bing Copilot", engine="bing_copilot", snippet=text,
                position=0, attrs={"ai_generated": True, "ai_answer": True})] if text else []
    out += [_obs(kind="article", name=r.get("title"), source=r.get("source") or "Bing Copilot source", engine="bing_copilot",
                 url=r.get("link"), snippet=r.get("snippet"), position=(r.get("index") or 0) + 1, attrs={"ai_reference": True})
            for r in data.get("references") or []]
    return out


def _p_bing(data: dict) -> list[dict]:
    return [_obs(kind="article", name=r.get("title"), source=r.get("displayed_link") or "Bing", engine="bing",
                 url=r.get("link"), snippet=r.get("snippet"), position=r.get("position"))
            for r in data.get("organic_results", []) or []]


def _p_events(data: dict) -> list[dict]:
    out = []
    for i, r in enumerate(data.get("events_results", []) or []):
        when = (r.get("date") or {}).get("when") or (r.get("date") or {}).get("start_date")
        venue = r.get("venue") or {}
        tickets = [t.get("source") for t in (r.get("ticket_info") or []) if t.get("source")]
        out.append(_obs(kind="event", name=r.get("title"), source="Google Events", engine="google_events",
                        url=r.get("link"), snippet=r.get("description"), address=", ".join(r.get("address") or []),
                        rating=venue.get("rating"), reviews=venue.get("reviews"), thumbnail=r.get("thumbnail"),
                        position=i + 1, attrs={k: v for k, v in {"when": when, "venue": venue.get("name"),
                                                                 "tickets": tickets[:3]}.items() if v}))
    return out


def _p_images(data: dict) -> list[dict]:
    return [_obs(kind="image", name=r.get("title"), source=r.get("source") or "Google Images", engine="google_images",
                 url=r.get("link"), thumbnail=r.get("thumbnail"), position=r.get("position"),
                 attrs={"original": r.get("original")})
            for r in (data.get("images_results") or [])[:12]]


def _p_finance(data: dict) -> list[dict]:
    s = data.get("summary") or {}
    out = []
    if s.get("title") or s.get("stock"):
        mv = s.get("price_movement") or {}
        out.append(_obs(kind="quote", name=f"{s.get('title') or s.get('stock')} ({s.get('stock')}:{s.get('exchange')})",
                        source="Google Finance", engine="google_finance", price=parse_price(s.get("extracted_price")),
                        currency=s.get("currency") or settings.currency, position=1,
                        attrs={k: v for k, v in {"movement": mv.get("movement"), "change_pct": mv.get("percentage"),
                                                 "change": mv.get("value"), "as_of": s.get("date")}.items() if v is not None}))
    for st in ((data.get("knowledge_graph") or {}).get("key_stats") or {}).get("stats") or []:
        if out and st.get("label"):
            out[0]["attrs"].setdefault("stats", {})[st["label"]] = st.get("value")
    for i, r in enumerate(data.get("news_results") or []):
        out.append(_obs(kind="article", name=r.get("snippet"), source=r.get("source") or "Google Finance news",
                        engine="google_finance", url=r.get("link"), attrs={"date": r.get("date")}, position=i + 2))
    return out


def _p_trends(data: dict) -> list[dict]:
    rows = ((data.get("interest_over_time") or {}).get("timeline_data")) or []
    if not rows:
        return []
    series: dict[str, list[float]] = {}
    for row in rows:
        for v in row.get("values") or []:
            series.setdefault(v.get("query") or "", []).append(float(v.get("extracted_value") or 0))
    out = []
    for i, (q, vals) in enumerate(series.items()):
        recent, earlier = vals[-4:], vals[:4]
        trend = (sum(recent) / len(recent)) - (sum(earlier) / len(earlier)) if recent and earlier else 0
        out.append(_obs(kind="trend", name=q, source="Google Trends", engine="google_trends", position=i + 1,
                        attrs={"latest": vals[-1], "peak": max(vals), "average": round(sum(vals) / len(vals), 1),
                               "direction": "rising" if trend > 5 else "falling" if trend < -5 else "steady",
                               "period": f"{rows[0].get('date')} – {rows[-1].get('date')}"}))
    return out


def _p_google_play(data: dict) -> list[dict]:
    out = []
    for group in data.get("organic_results", []) or []:
        for r in group.get("items", []) or []:
            out.append(_obs(kind="app", name=r.get("title"), source="Google Play", engine="google_play", url=r.get("link"),
                            id=r.get("product_id"), rating=r.get("rating"), snippet=r.get("description"),
                            thumbnail=r.get("thumbnail"), position=len(out) + 1,
                            attrs={k: v for k, v in {"developer": r.get("author"), "category": r.get("category"),
                                                     "downloads": r.get("downloads")}.items() if v}))
    return out


def _p_app_store(data: dict) -> list[dict]:
    out = []
    for r in data.get("organic_results", []) or []:
        ratings = r.get("rating") or []
        cur = next((x for x in ratings if x.get("type") == "All Times"), ratings[0] if ratings else {})
        out.append(_obs(kind="app", name=r.get("title"), source="Apple App Store", engine="apple_app_store",
                        url=r.get("link"), id=str(r.get("id") or ""), rating=cur.get("rating"), reviews=cur.get("count"),
                        snippet=(r.get("description") or "")[:300], position=r.get("position"),
                        attrs={k: v for k, v in {"developer": (r.get("developer") or {}).get("name"),
                                                 "price": (r.get("price") or {}).get("type")}.items() if v}))
    return out


def _p_jobs(data: dict) -> list[dict]:
    return [_obs(kind="job", name=f"{r.get('title')} — {r.get('company_name')}", source=f"Google Jobs · {r.get('via', '')}",
                 engine="google_jobs", url=(r.get("apply_options") or [{}])[0].get("link"),
                 attrs={"location": r.get("location"), **(r.get("detected_extensions") or {})})
            for r in data.get("jobs_results", [])]


def _p_directions(data: dict) -> list[dict]:
    out = []
    for d in data.get("directions", []) or []:
        out.append(_obs(kind="route", name=d.get("via") or d.get("travel_mode") or "Route", source="Google Maps Directions",
                        engine="google_maps_directions",
                        attrs={"mode": d.get("travel_mode"), "distance_km": (d.get("distance") or 0) / 1000 if isinstance(d.get("distance"), (int, float)) else None,
                               "duration_min": (d.get("duration") or 0) / 60 if isinstance(d.get("duration"), (int, float)) else None,
                               "formatted_duration": d.get("formatted_duration"), "cost": d.get("cost")}))
    return out


# ---------------------------------------------------------------- capabilities
def _gl() -> dict:
    return {"gl": settings.country, "hl": settings.language}


def search_web(query: str, forums: bool = True, overview: bool = False) -> dict:
    calls = [("google", {"q": query, **_gl(), **({"__overview": True} if overview else {})}, _p_google)]
    if forums:
        calls.append(("google", {"q": f"{query} reddit OR forum", **_gl()}, _p_google))
    return _result("search_web", calls)


def research_product(query: str, budget_max: float | None = None, country: str | None = None) -> dict:
    country = (country or settings.country).lower()
    hint = {"__budget": budget_max}
    calls: list = [("google_shopping", {"q": query, **_gl(), **hint}, _p_shopping)]
    if country == "in":
        calls.append(("amazon", {"k": query, "amazon_domain": settings.amazon_domain, **hint}, _p_amazon))
    else:
        calls += [("amazon", {"k": query, "amazon_domain": "amazon.com", **hint}, _p_amazon),
                  ("ebay", {"_nkw": query, "ebay_domain": "ebay.com", **hint}, _p_ebay),
                  ("walmart", {"query": query, **hint}, _p_walmart)]
    return _result("research_product", calls)


def find_local_places(query: str, lat: float | None, lng: float | None, zoom: int = 14) -> dict:
    params: dict = {"q": query, "type": "search", "hl": settings.language}
    if lat is not None and lng is not None:
        params["ll"] = f"@{lat},{lng},{zoom}z"
    return _result("find_local_places", [("google_maps", params, _p_maps)])


def find_route(origin: str, destination: str, mode: str = "transit") -> dict:
    mode_code = {"driving": 0, "two_wheeler": 9, "transit": 3, "walking": 2, "cycling": 1}.get(mode, 3)
    return _result("find_route", [("google_maps_directions",
                                   {"start_addr": origin, "end_addr": destination, "travel_mode": mode_code,
                                    "hl": settings.language}, _p_directions)])


def research_travel(origin_city: str, dest_city: str, depart_date: str | None,
                    origin_airport: str | None = None, dest_airport: str | None = None) -> dict:
    depart_date = depart_date or (date.today() + timedelta(days=1)).isoformat()
    calls: list = []
    if origin_airport and dest_airport:
        calls.append(("google_flights", {"departure_id": origin_airport, "arrival_id": dest_airport,
                                         "outbound_date": depart_date, "type": 2, "currency": settings.currency,
                                         **_gl()}, _p_flights))
    calls.append(("google", {"q": f"{origin_city} to {dest_city} train ticket price duration", **_gl()}, _p_google))
    calls.append(("google", {"q": f"{origin_city} to {dest_city} bus ticket price duration", **_gl()}, _p_google))
    return _result("research_travel", calls, {"route": {"from": origin_city, "to": dest_city, "date": depart_date}})


def research_hotels(query: str, check_in: str, check_out: str) -> dict:
    return _result("research_hotels", [("google_hotels", {"q": query, "check_in_date": check_in,
                                                          "check_out_date": check_out, "currency": settings.currency,
                                                          **_gl()}, _p_hotels)])


def research_hotels_and_rentals(query: str, check_in: str, check_out: str, adults: int = 1,
                                max_price: float | None = None, rentals: bool = True) -> dict:
    hp = {"q": query, "check_in_date": check_in, "check_out_date": check_out, "adults": adults,
          "currency": settings.currency, **_gl()}
    if max_price:
        hp["max_price"] = int(max_price)
    calls: list = [("google_hotels", hp, _p_hotels)]
    if rentals:
        calls.append(("airbnb", {"q": query, "check_in_date": check_in, "check_out_date": check_out,
                                 "adults": adults, "currency": settings.currency}, _p_airbnb))
    return _result("research_stays", calls)


TRIPADVISOR_CATEGORY = {"all": "a", "restaurants": "r", "things_to_do": "A", "hotels": "h", "destinations": "g", "forums": "f"}


def search_tripadvisor(query: str, category: str = "all") -> dict:
    return _result("search_tripadvisor", [("tripadvisor", {"q": query, "ssrc": TRIPADVISOR_CATEGORY.get(category, "a"),
                                                          "limit": 15}, _p_tripadvisor)])


def ask_ai_mode(query: str) -> dict:
    """Google AI Mode: a written, source-linked answer to any question (used when Claude is unavailable
    and as extra evidence when it is)."""
    return _result("ask_ai_mode", [("google_ai_mode", {"q": query, **_gl()}, _p_ai_mode)])


def explore_destinations(from_airport: str, outbound_date: str | None = None, weekend: bool = True,
                         max_price: float | None = None) -> dict:
    params = {"departure_id": from_airport.upper(), "travel_duration": 1 if weekend else 2, "currency": settings.currency, **_gl()}
    if outbound_date:
        params["outbound_date"] = outbound_date
    if max_price:
        params["max_price"] = int(max_price)
    return _result("explore_destinations", [("google_travel_explore", params, _p_travel_explore)])


def place_reviews(query: str, lat: float | None = None, lng: float | None = None) -> dict:
    """Find the place on Maps, then read what reviewers actually say about it (2 searches)."""
    found = find_local_places(query, lat, lng)
    top = next((o for o in found["observations"] if (o.get("attrs") or {}).get("data_id") or o.get("id")), None)
    if not top:
        return found
    rid = (top.get("attrs") or {}).get("data_id")
    params = {"data_id": rid} if rid else {"place_id": top["id"]}
    rev = _result("place_reviews", [("google_maps_reviews", {**params, "hl": settings.language, "sort_by": "qualityScore"},
                                     _p_maps_reviews)])
    return {**rev, "observations": [top] + rev["observations"], "calls": found["calls"] + rev["calls"]}


def hotel_reviews(property_token: str) -> dict:
    return _result("hotel_reviews", [("google_hotels_reviews", {"property_token": property_token, "hl": settings.language},
                                      _p_hotel_reviews)])


def market_overview() -> dict:
    return _result("market_overview", [("google_finance_markets", {"trend": "indexes", **_gl()}, _p_markets)])


def trending_now(geo: str | None = None, hours: int = 24) -> dict:
    return _result("trending_now", [("google_trends_trending_now", {"geo": (geo or settings.country).upper(), "hours": hours},
                                     _p_trending_now)])


def search_web_more(query: str) -> dict:
    """Extra independent web indexes (DuckDuckGo + Yahoo) for coverage or when others come back thin."""
    return _result("search_web_more", [("duckduckgo", {"q": query, "kl": f"{settings.country}-{settings.language}"},
                                        _p_simple_organic("DuckDuckGo", "duckduckgo")),
                                       ("yahoo", {"p": query, "vc": settings.country}, _p_simple_organic("Yahoo", "yahoo"))])


def news_alt(query: str) -> dict:
    return _result("news_alt", [("bing_news", {"q": query, "cc": settings.country}, _p_simple_organic("Bing News", "bing_news"))])


def ask_bing_copilot(query: str) -> dict:
    return _result("ask_bing_copilot", [("bing_copilot", {"q": query}, _p_bing_copilot)])


def search_web_alt(query: str) -> dict:
    """Second web index (Bing) — used as a fallback when Google returns too little."""
    return _result("search_web_alt", [("bing", {"q": query, "cc": settings.country}, _p_bing)])


EVENT_WHEN = {"today": "date:today", "tomorrow": "date:tomorrow", "week": "date:week", "weekend": "date:week",
              "next_week": "date:next_week", "month": "date:month", "next_month": "date:next_month"}


def find_events(query: str, when: str | None = None) -> dict:
    params = {"q": query, **_gl()}
    if when in EVENT_WHEN:
        params["htichips"] = EVENT_WHEN[when]
    return _result("find_events", [("google_events", params, _p_events)])


def search_images(query: str) -> dict:
    return _result("search_images", [("google_images", {"q": query, **_gl()}, _p_images)])


def market_quote(symbol: str) -> dict:
    return _result("market_quote", [("google_finance", {"q": symbol, "hl": settings.language}, _p_finance)])


def search_trends(query: str, geo: str | None = None) -> dict:
    terms = ",".join(t.strip() for t in query.split(",")[:5] if t.strip())
    return _result("search_trends", [("google_trends", {"q": terms, "data_type": "TIMESERIES", "date": "today 12-m",
                                                        "geo": (geo or settings.country).upper()}, _p_trends)])


def search_apps(query: str) -> dict:
    return _result("search_apps", [("google_play", {"q": query, **_gl()}, _p_google_play),
                                   ("apple_app_store", {"term": query, "country": settings.country, "num": 10},
                                    _p_app_store)])


def research_news(query: str) -> dict:
    return _result("research_news", [("google_news", {"q": query, **_gl()}, _p_news)])


def research_academic(query: str) -> dict:
    return _result("research_academic", [
        ("google_scholar", {"q": query, "hl": settings.language}, _p_scholar("google_scholar")),
        ("google_patents", {"q": query}, _p_scholar("google_patents")),
        ("google_news", {"q": query, **_gl()}, _p_news),
    ])


def research_jobs(query: str, location: str | None = None) -> dict:
    return _result("research_jobs", [("google_jobs", {"q": query, "location": location, "hl": settings.language}, _p_jobs)])


def research_video(query: str) -> dict:
    return _result("research_video", [("youtube", {"search_query": query, "gl": settings.country}, _p_youtube)])


def analyze_image(image_url: str) -> dict:
    res = _result("analyze_image", [("google_lens", {"url": image_url, "hl": settings.language,
                                                     "country": settings.country}, _p_lens)])
    titles = [o["name"] for o in res["observations"] if o.get("name")]
    res["identified_as"] = _most_common_title(titles)
    return res


def _most_common_title(titles: list[str]) -> str | None:
    """Pick the product identity most visual matches agree on (token overlap vote)."""
    if not titles:
        return None
    def toks(t: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}
    best, best_score = titles[0], -1.0
    for t in titles:
        a = toks(t)
        score = sum(len(a & toks(o)) / (len(a | toks(o)) or 1) for o in titles if o is not t)
        if score > best_score:
            best, best_score = t, score
    return re.split(r"\s[-|–]\s", best)[0].strip()


CAPABILITIES: dict[str, Callable[..., dict]] = {
    "search_web": search_web,
    "research_product": research_product,
    "find_local_places": find_local_places,
    "find_route": find_route,
    "research_travel": research_travel,
    "research_hotels": research_hotels,
    "research_news": research_news,
    "research_academic": research_academic,
    "research_jobs": research_jobs,
    "research_video": research_video,
    "analyze_image": analyze_image,
    "research_stays": research_hotels_and_rentals,
    "search_tripadvisor": search_tripadvisor,
    "search_web_alt": search_web_alt,
    "ask_ai_mode": ask_ai_mode,
    "ask_bing_copilot": ask_bing_copilot,
    "explore_destinations": explore_destinations,
    "place_reviews": place_reviews,
    "hotel_reviews": hotel_reviews,
    "market_overview": market_overview,
    "trending_now": trending_now,
    "search_web_more": search_web_more,
    "news_alt": news_alt,
    "find_events": find_events,
    "search_images": search_images,
    "market_quote": market_quote,
    "search_trends": search_trends,
    "search_apps": search_apps,
}
