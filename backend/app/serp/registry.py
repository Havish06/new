"""Tool registry: every SerpApi-backed capability the research planner may use.

The planner (Claude or the rule fallback) only ever names tools from this registry and fills their
declared args; it never sees engine names, URLs or raw parameters. `run_tool` validates the args
and calls the capability, so adding an API later means: write a capability + parser in
capabilities.py, then add one entry here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

from . import capabilities as cap


@dataclass(frozen=True)
class Tool:
    name: str
    purpose: str                       # shown to the planner and in the UI
    args: dict[str, str]               # arg -> description; first arg is the main query
    required: tuple[str, ...]
    run: Callable[[dict, dict], dict]  # (args, context) -> capability result
    engines: tuple[str, ...]
    cost: int = 1                      # SerpApi searches per call
    fallback: str | tuple[str, ...] | None = None   # tool(s) to try, in order, when this one returns nothing
    tags: tuple[str, ...] = field(default_factory=tuple)


def _dates(a: dict) -> tuple[str, str]:
    ci = a.get("check_in") or (date.today() + timedelta(days=7)).isoformat()
    try:
        co = a.get("check_out") or (date.fromisoformat(ci) + timedelta(days=1)).isoformat()
    except ValueError:
        co = (date.today() + timedelta(days=8)).isoformat()
    return ci, co


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("web_search", "General web research (Google): facts, guides, comparisons, how-to, anything",
         {"q": "search query"}, ("q",), lambda a, c: cap.search_web(a["q"], forums=False, overview=True),
         ("google", "google_ai_overview"), fallback=("web_search_alt", "web_search_more")),
    Tool("web_search_alt", "Second web index (Bing) for extra coverage or when Google returns little",
         {"q": "search query"}, ("q",), lambda a, c: cap.search_web_alt(a["q"]), ("bing",), fallback="web_search_more"),
    Tool("web_search_more", "More independent web indexes (DuckDuckGo + Yahoo) for wider coverage",
         {"q": "search query"}, ("q",), lambda a, c: cap.search_web_more(a["q"]), ("duckduckgo", "yahoo"), cost=2),
    Tool("ai_answer", "Google AI Mode: a written, source-linked answer to the question (use for explanations, "
         "itineraries, how-to, comparisons — any question that needs a synthesised answer)",
         {"q": "the question, phrased naturally"}, ("q",), lambda a, c: cap.ask_ai_mode(a["q"]), ("google_ai_mode",),
         fallback=("ai_answer_alt", "web_search")),
    Tool("ai_answer_alt", "Bing Copilot: a second AI-written answer with sources",
         {"q": "the question"}, ("q",), lambda a, c: cap.ask_bing_copilot(a["q"]), ("bing_copilot",)),
    Tool("forum_search", "Real user opinions and experiences (Reddit / forums)",
         {"q": "topic"}, ("q",), lambda a, c: cap.search_web(f"{a['q']} reddit OR forum", forums=False), ("google",)),
    Tool("news_search", "Latest news and current events, with publication dates",
         {"q": "topic"}, ("q",), lambda a, c: cap.research_news(a["q"]), ("google_news",), fallback=("news_alt", "web_search")),
    Tool("news_alt", "News from Bing News (second news index)", {"q": "topic"}, ("q",),
         lambda a, c: cap.news_alt(a["q"]), ("bing_news",)),
    Tool("product_search", "Products to buy: prices, ratings and sellers (Google Shopping + Amazon)",
         {"q": "product", "budget_max": "max price (number, optional)"}, ("q",),
         lambda a, c: cap.research_product(a["q"], _num(a.get("budget_max"))), ("google_shopping", "amazon"), cost=2),
    Tool("local_places", "Places/businesses near a location: ratings, reviews, hours, address (Google Maps)",
         {"q": "place type + area, e.g. 'momos near MG Marg Gangtok'",
          "near_me": "true only when searching around the user's own location"}, ("q",),
         lambda a, c: cap.find_local_places(a["q"], *(_near(a, c))), ("google_maps",), fallback="web_search"),
    Tool("place_reviews", "What reviewers actually say about one specific place (Google Maps reviews + topics)",
         {"q": "place name + area"}, ("q",), lambda a, c: cap.place_reviews(a["q"], *(_near(a, c))),
         ("google_maps", "google_maps_reviews"), cost=2),
    Tool("directions", "Route, distance and travel time between two places (Google Maps Directions)",
         {"from": "origin", "to": "destination", "mode": "driving|transit|walking|two_wheeler"}, ("from", "to"),
         lambda a, c: cap.find_route(a["from"], a["to"], a.get("mode") or "driving"), ("google_maps_directions",)),
    Tool("flights", "Flight options and fares between two airports on a date (Google Flights)",
         {"from_airport": "IATA code", "to_airport": "IATA code", "date": "YYYY-MM-DD",
          "from_city": "origin city", "to_city": "destination city"}, ("from_airport", "to_airport"),
         lambda a, c: cap.research_travel(a.get("from_city") or a["from_airport"], a.get("to_city") or a["to_airport"],
                                          a.get("date"), a["from_airport"], a["to_airport"]),
         ("google_flights", "google"), cost=3),
    Tool("stays", "Hotels and vacation rentals with prices for specific dates (Google Hotels + Airbnb)",
         {"q": "area or city", "check_in": "YYYY-MM-DD", "check_out": "YYYY-MM-DD", "adults": "number",
          "max_price": "max nightly price (optional)"}, ("q",),
         lambda a, c: cap.research_hotels_and_rentals(a["q"], *_dates(a), int(_num(a.get("adults")) or 1),
                                                      _num(a.get("max_price"))), ("google_hotels", "airbnb"), cost=2),
    Tool("tripadvisor", "Travel discovery: destinations, things to do, restaurants, hotels (Tripadvisor)",
         {"q": "place or topic", "category": "destinations|things_to_do|restaurants|hotels|all"}, ("q",),
         lambda a, c: cap.search_tripadvisor(a["q"], a.get("category") or "all"), ("tripadvisor",),
         fallback="web_search"),
    Tool("events", "Concerts, shows, meetups and things happening (Google Events)",
         {"q": "events + city", "when": "today|tomorrow|week|weekend|next_week|month|next_month"}, ("q",),
         lambda a, c: cap.find_events(a["q"], a.get("when")), ("google_events",), fallback="web_search"),
    Tool("jobs", "Job openings and internships (Google Jobs)",
         {"q": "role", "location": "city (optional)"}, ("q",),
         lambda a, c: cap.research_jobs(a["q"], a.get("location")), ("google_jobs",), fallback="web_search"),
    Tool("videos", "Videos and tutorials (YouTube)", {"q": "topic"}, ("q",),
         lambda a, c: cap.research_video(a["q"]), ("youtube",)),
    Tool("images", "Pictures of something (Google Images) — only when the user wants to see images",
         {"q": "subject"}, ("q",), lambda a, c: cap.search_images(a["q"]), ("google_images",)),
    Tool("scholar", "Research papers and patents (Google Scholar + Patents + News)", {"q": "topic"}, ("q",),
         lambda a, c: cap.research_academic(a["q"]), ("google_scholar", "google_patents", "google_news"), cost=3),
    Tool("trends", "Search-interest over the last 12 months (Google Trends); comma-separate up to 5 terms to compare",
         {"q": "term(s)"}, ("q",), lambda a, c: cap.search_trends(a["q"]), ("google_trends",)),
    Tool("markets", "Today's market overview: major indexes, currencies, crypto, futures (Google Finance Markets)",
         {}, (), lambda a, c: cap.market_overview(), ("google_finance_markets",), fallback="news_search"),
    Tool("trending_now", "What people are searching for right now in the user's country (Google Trends Trending Now)",
         {"hours": "4|24|48|168"}, (), lambda a, c: cap.trending_now(None, int(_num(a.get("hours")) or 24)),
         ("google_trends_trending_now",)),
    Tool("explore_destinations", "Destinations reachable by air with current flight prices (Google Travel Explore)",
         {"from_airport": "IATA code", "outbound_date": "YYYY-MM-DD (optional)", "weekend": "true|false"}, ("from_airport",),
         lambda a, c: cap.explore_destinations(a["from_airport"], a.get("outbound_date"),
                                               str(a.get("weekend", "true")).lower() != "false"), ("google_travel_explore",)),
    Tool("hotel_reviews", "Guest reviews and sub-scores for a hotel found by the stays tool (Google Hotels Reviews)",
         {"property_token": "token from a stays result"}, ("property_token",),
         lambda a, c: cap.hotel_reviews(a["property_token"]), ("google_hotels_reviews",)),
    Tool("finance", "Live stock / index / currency quote and key stats (Google Finance)",
         {"symbol": "TICKER:EXCHANGE, e.g. RELIANCE:NSE, GOOG:NASDAQ, NIFTY_50:INDEXNSE, USD-INR"}, ("symbol",),
         lambda a, c: cap.market_quote(a["symbol"]), ("google_finance",), fallback="web_search"),
    Tool("apps", "Mobile apps with ratings (Google Play + Apple App Store)", {"q": "what the app should do"}, ("q",),
         lambda a, c: cap.search_apps(a["q"]), ("google_play", "apple_app_store"), cost=2),
]}


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _near(a: dict, c: dict) -> tuple[float | None, float | None]:
    """Centre the map on the user's home only when the query is about their own area."""
    loc = c.get("location") or {}
    near = a.get("near_me")
    if near is None:
        q = str(a.get("q") or "").lower()
        near = bool(re.search(r"\bnear (?:me|by)\b|\bnearby\b", q)) or not re.search(r"\b(?:in|near|at|around)\s+\w", q)
    if str(near).lower() in ("false", "0", "no"):
        return None, None
    return loc.get("lat"), loc.get("lng")


def catalog() -> str:
    """Compact tool list for the planner prompt."""
    return "\n".join(f"- {t.name}: {t.purpose}. args: {t.args}" for t in TOOLS.values())


def fallbacks(tool: str) -> tuple[str, ...]:
    fb = TOOLS[tool].fallback
    return () if not fb else (fb,) if isinstance(fb, str) else fb


def validate(tool: str, args: Any) -> tuple[dict | None, str | None]:
    t = TOOLS.get(tool)
    if not t:
        return None, f"unknown tool {tool!r}"
    if not isinstance(args, dict):
        return None, "args must be an object"
    clean = {k: v for k, v in args.items() if k in t.args and v not in (None, "")}
    missing = [r for r in t.required if not clean.get(r)]
    if missing:
        return None, f"{tool} needs {', '.join(missing)}"
    return clean, None


def run_tool(tool: str, args: dict, context: dict) -> dict:
    return TOOLS[tool].run(args, context)
