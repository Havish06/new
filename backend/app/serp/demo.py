"""Deterministic, SerpApi-shaped demo responses.

Used when SERPAPI_KEY is not configured or DEMO_MODE=true. Output follows the real response
schemas closely enough that parsing, evidence fusion and scoring run exactly as in live mode.
Every response is flagged `search_metadata.demo = true` and the UI labels it as demo data.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from datetime import datetime, timedelta
from typing import Any

# Product lines per category: (name, base_price_inr, rating, reviews, attributes)
CATALOG: dict[str, list[tuple[str, int, float, int, dict]]] = {
    "laptop": [
        ("ASUS Vivobook 16 Ryzen 7 7735HS 16GB/512GB", 62990, 4.3, 2140, {"ram_gb": 16, "weight_kg": 1.8, "battery_h": 8}),
        ("Lenovo IdeaPad Slim 5 Core i5-13420H 16GB/512GB", 64490, 4.4, 1870, {"ram_gb": 16, "weight_kg": 1.46, "battery_h": 11}),
        ("HP Pavilion Plus 14 Core i5-1340P 16GB/512GB OLED", 68999, 4.2, 960, {"ram_gb": 16, "weight_kg": 1.4, "battery_h": 9}),
        ("Acer Aspire 7 Ryzen 5 5500U RTX 3050 8GB/512GB", 54990, 4.0, 3310, {"ram_gb": 8, "weight_kg": 2.1, "battery_h": 5}),
        ("Dell Inspiron 14 Core i5-1335U 16GB/512GB", 59990, 4.1, 1220, {"ram_gb": 16, "weight_kg": 1.54, "battery_h": 8}),
        ("MSI Modern 15 Core i7-1255U 16GB/512GB", 57990, 3.9, 740, {"ram_gb": 16, "weight_kg": 1.7, "battery_h": 7}),
        ("Apple MacBook Air M2 8GB/256GB", 79900, 4.7, 5400, {"ram_gb": 8, "weight_kg": 1.24, "battery_h": 18}),
        ("Lenovo LOQ Ryzen 7 7840HS RTX 4060 16GB/512GB", 84990, 4.4, 1530, {"ram_gb": 16, "weight_kg": 2.4, "battery_h": 5}),
    ],
    "headphone": [
        ("Sony WH-CH720N Wireless ANC Headphones", 7990, 4.3, 8900, {"battery_h": 35, "anc": True}),
        ("JBL Tune 770NC Wireless ANC Headphones", 5999, 4.2, 6120, {"battery_h": 44, "anc": True}),
        ("boAt Rockerz 551ANC Headphones", 2499, 3.9, 21400, {"battery_h": 100, "anc": True}),
        ("Soundcore by Anker Space Q45", 7999, 4.4, 3300, {"battery_h": 50, "anc": True}),
        ("Sennheiser HD 450BT", 8490, 4.2, 2800, {"battery_h": 30, "anc": True}),
        ("OnePlus Bullets Wireless Z2 ANC", 1999, 4.1, 40100, {"battery_h": 28, "anc": True}),
        ("Noise Airwave Max 4 ANC Headphones", 3299, 4.0, 5200, {"battery_h": 70, "anc": True}),
    ],
    "shoe": [
        ("Bata Men's Formal Oxford Lace-Up Shoes", 1799, 4.1, 3120, {}),
        ("Red Tape Men's Leather Formal Derby", 1599, 4.2, 9800, {}),
        ("Hush Puppies Men's Classic Formal Shoes", 3499, 4.4, 1900, {}),
        ("Woodland Men's Leather Formal Shoes", 2995, 4.3, 2400, {}),
        ("Centrino Men's Synthetic Formal Shoes", 899, 3.8, 15400, {}),
        ("Nike Revolution 7 Running Shoes", 3695, 4.3, 7100, {}),
    ],
    "usb": [
        ("SanDisk Ultra Dual Drive 64GB USB 3.0", 549, 4.4, 61000, {}),
        ("HP v236w 32GB USB 2.0 Pen Drive", 299, 4.2, 38000, {}),
        ("Kingston DataTraveler Exodia 64GB", 449, 4.3, 22000, {}),
        ("SanDisk Cruzer Blade 32GB", 279, 4.3, 120000, {}),
    ],
    "phone": [
        ("Samsung Galaxy M35 5G 8GB/128GB", 15999, 4.2, 12000, {"battery_mah": 6000}),
        ("Redmi Note 14 5G 8GB/128GB", 17999, 4.1, 8800, {"battery_mah": 5110}),
        ("iQOO Z9 5G 8GB/128GB", 19999, 4.3, 15000, {"battery_mah": 5000}),
        ("Motorola Edge 50 Fusion 8GB/128GB", 22999, 4.3, 9900, {"battery_mah": 5000}),
        ("Nothing Phone (2a) 8GB/128GB", 23999, 4.4, 11000, {"battery_mah": 5000}),
    ],
}

STORES = ["Amazon.in", "Flipkart", "Croma", "Reliance Digital", "Vijay Sales", "Tata CLiQ"]

PLACE_NAMES = {
    "print": ["Sri Murugan Xerox & Printing", "QuickPrint Digital Centre", "Anna Xerox Point", "Star Print Hub"],
    "photo": ["Lakshmi Studio & Passport Photos", "Click Digital Studio", "Snap Express Photo Shop"],
    "repair": ["LaptopCare Service Centre", "TechFix Computer Repairs", "Sai Laptop Clinic", "Digital Doctor Repairs"],
    "shoe": ["Bata Store", "Metro Shoes", "Regal Footwear", "Woodland Exclusive Store"],
    "usb": ["Sri Balaji Computers", "Reliance Digital", "Poorvika Mobiles & Accessories"],
    "restaurant": ["Saravana Bhavan", "Annapoorna Veg Restaurant", "The Brew Room Cafe", "Junior Kuppanna"],
    "cafe": ["Third Wave Coffee", "The Brew Room", "Chai Kings", "Blue Tokai Coffee"],
    "hospital": ["City Care Multispeciality Hospital", "Apollo Clinic", "Kauvery Medical Centre"],
}


def _rng(*parts: Any) -> random.Random:
    seed = int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)
    return random.Random(seed)


def _category(q: str) -> str | None:
    q = q.lower()
    for key, words in {
        "laptop": ["laptop", "notebook", "macbook"],
        "headphone": ["headphone", "earphone", "headset", "earbud", "anc"],
        "shoe": ["shoe", "sneaker", "footwear", "oxford", "derby"],
        "usb": ["usb", "pen drive", "pendrive", "flash drive"],
        "phone": ["phone", "smartphone", "mobile"],
    }.items():
        if any(w in q for w in words):
            return key
    return None


def _generic_products(q: str, budget: float | None) -> list[tuple[str, int, float, int, dict]]:
    r = _rng("generic", q)
    base = int(budget * 0.8) if budget else r.randint(800, 20000)
    noun = re.sub(r"\b(best|buy|under|cheap|good|for|me|a|the|\d+[k]?|rs|inr|₹)\b", " ", q, flags=re.I)
    noun = " ".join(noun.split()).title() or "Product"
    brands = ["Prime", "Nova", "Zenith", "Aero", "Orbit", "Pulse", "Vertex"]
    out = []
    for i, b in enumerate(brands):
        price = max(99, int(base * r.uniform(0.6, 1.35)))
        out.append((f"{b} {noun} {['Lite', 'Pro', 'Plus', 'Max', 'Neo', 'X', 'Air'][i]}",
                    price, round(r.uniform(3.6, 4.7), 1), r.randint(80, 9000), {}))
    return out


def _products(q: str, hints: dict) -> list[tuple[str, int, float, int, dict]]:
    cat = _category(q)
    budget = hints.get("__budget")
    return CATALOG[cat] if cat else _generic_products(q, budget)


def _fmt_inr(v: float) -> str:
    return "₹" + f"{int(round(v)):,}"


def _shopping(q: str, hints: dict) -> dict:
    out = []
    for i, (name, price, rating, reviews, attrs) in enumerate(_products(q, hints)):
        r = _rng("gs", name)
        p = int(price * r.uniform(0.94, 1.03))
        out.append({
            "position": i + 1, "title": name, "price": _fmt_inr(p), "extracted_price": p,
            "source": r.choice(STORES), "rating": rating, "reviews": int(reviews * 0.6),
            "delivery": r.choice(["Free delivery", "Free delivery by tomorrow", "Delivery in 3-5 days"]),
            "product_link": f"https://www.google.com/shopping/product/{abs(hash(name)) % 10**10}",
            "thumbnail": "", "product_id": str(abs(hash(name)) % 10**12),
            "extensions": [f"{k.replace('_', ' ')}: {v}" for k, v in attrs.items()],
        })
    return {"shopping_results": out}


def _amazon(q: str, hints: dict) -> dict:
    out = []
    for i, (name, price, rating, reviews, attrs) in enumerate(_products(q, hints)):
        r = _rng("amz", name)
        p = int(price * r.uniform(0.98, 1.06))
        asin = "B0" + hashlib.md5(name.encode()).hexdigest()[:8].upper()
        out.append({
            "position": i + 1, "asin": asin, "title": name,
            "link": f"https://www.amazon.in/dp/{asin}", "rating": rating, "reviews": reviews,
            "price": _fmt_inr(p), "extracted_price": p,
            "delivery": [r.choice(["FREE delivery Tomorrow", "FREE delivery Sat", "FREE delivery in 4 days"])],
            "thumbnail": "",
        })
    return {"organic_results": out}


def _ebay(q: str, hints: dict) -> dict:
    out = []
    for i, (name, price, rating, reviews, _) in enumerate(_products(q, hints)[:5]):
        r = _rng("ebay", name)
        usd = round(price / 83 * r.uniform(0.85, 1.0), 2)
        out.append({"position": i + 1, "title": name, "link": f"https://www.ebay.com/itm/{abs(hash(name)) % 10**12}",
                    "price": {"raw": f"${usd}", "extracted": usd}, "condition": r.choice(["Brand New", "Pre-Owned"]),
                    "reviews": int(reviews * 0.05), "rating": rating})
    return {"organic_results": out}


def _parse_ll(ll: str | None) -> tuple[float, float]:
    m = re.match(r"@?(-?\d+\.?\d*),(-?\d+\.?\d*)", ll or "")
    return (float(m.group(1)), float(m.group(2))) if m else (13.0827, 80.2707)  # Chennai fallback


def _place_kind(q: str) -> str:
    ql = q.lower()
    for k, words in {"print": ["print", "xerox", "photocop"], "photo": ["passport", "photo studio", "photo"],
                     "repair": ["repair", "service"], "shoe": ["shoe", "footwear"], "usb": ["usb", "pen drive", "computer shop", "electronics"],
                     "restaurant": ["restaurant", "food", "lunch", "dinner"], "cafe": ["cafe", "coffee"],
                     "hospital": ["hospital", "clinic", "doctor"]}.items():
        if any(w in ql for w in words):
            return k
    return "generic"


def _maps(q: str, ll: str | None) -> dict:
    lat, lng = _parse_ll(ll)
    kind = _place_kind(q)
    names = PLACE_NAMES.get(kind) or [f"{q.title()} {s}" for s in ("Centre", "Hub", "Point", "Store")]
    price = {"print": "₹1–100", "photo": "₹100–200", "repair": "₹500–2,000", "usb": "₹200–600",
             "shoe": "₹1,000–3,000", "restaurant": "₹200–400", "cafe": "₹200–400"}.get(kind)
    out = []
    for i, name in enumerate(names):
        r = _rng("map", name, round(lat, 2), round(lng, 2))
        dist_km = r.uniform(0.3, 4.5)
        ang = r.uniform(0, 2 * math.pi)
        plat = lat + (dist_km / 111) * math.sin(ang)
        plng = lng + (dist_km / (111 * math.cos(math.radians(lat)))) * math.cos(ang)
        close = r.choice([20, 21, 21, 22])
        out.append({
            "position": i + 1, "title": name, "place_id": "demo_" + hashlib.md5(name.encode()).hexdigest()[:16],
            "data_id": "0x" + hashlib.md5(name.encode()).hexdigest()[:16],
            "rating": round(r.uniform(3.7, 4.8), 1), "reviews": r.randint(25, 900),
            "price": price, "type": kind.title() if kind != "generic" else "Business",
            "address": f"{r.randint(1, 220)}, {r.choice(['Anna Salai', 'Mount Road', 'GST Road', 'Main Road', 'Station Road'])}",
            "gps_coordinates": {"latitude": round(plat, 6), "longitude": round(plng, 6)},
            "open_state": f"Open ⋅ Closes {close - 12} PM",
            "operating_hours": {d: f"9 AM–{close - 12} PM" for d in
                                ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")},
            "phone": f"+91 9{r.randint(100000000, 999999999)}",
        })
    return {"local_results": out}


def _news(q: str) -> dict:
    r = _rng("news", q)
    now = datetime.now()
    outlets = ["The Hindu", "Times of India", "Mint", "The Economic Times", "NDTV", "Hindustan Times"]
    angles = ["latest developments in", "what experts say about", "prices and availability of",
              "policy update on", "how consumers are responding to", "analysis:"]
    return {"news_results": [{
        "position": i + 1, "title": f"{a.capitalize()} {q}", "link": f"https://example.com/news/{i}",
        "source": {"name": r.choice(outlets)}, "date": (now - timedelta(hours=r.randint(2, 200))).strftime("%m/%d/%Y"),
        "snippet": f"Demo coverage summarising {a} {q}."} for i, a in enumerate(angles)]}


DEMO_DESTINATIONS = {"Pondicherry": (11.94, 79.83), "Kodaikanal": (10.24, 77.49), "Yelagiri": (12.58, 78.64),
                     "Tirupati": (13.63, 79.42), "Ooty": (11.41, 76.70), "Munnar": (10.09, 77.06),
                     "Mysore": (12.30, 76.64), "Coorg": (12.42, 75.74)}


def _google(q: str) -> dict:
    r = _rng("g", q)
    if re.search(r"places to visit|trips? from|getaways?", q.lower()):
        names = list(DEMO_DESTINATIONS)
        organic = [{"position": i + 1, "title": f"{t} — demo travel guide", "link": f"https://example.com/trips/{i}",
                    "source": "example.com",
                    "snippet": " · ".join(f"{j + 1}. {n}" for j, n in enumerate(r.sample(names, 5)))}
                   for i, t in enumerate(["Best Trips from Chennai", "Weekend Getaways", "Short Trips Guide", "Top Escapes"])]
        return {"organic_results": organic}
    sites = ["reddit.com", "quora.com", "wikipedia.org", "rtings.com", "91mobiles.com", "smartprix.com", "geeksforgeeks.org"]
    organic = [{"position": i + 1, "title": f"{q.title()} — {s.split('.')[0].title()} guide",
                "link": f"https://{s}/{re.sub(r'[^a-z0-9]+', '-', q.lower())}",
                "source": s, "snippet": f"Demo result from {s} discussing {q}: comparisons, user opinions and tips."}
               for i, s in enumerate(r.sample(sites, 6))]
    forums = [{"title": f"r/india — Opinions on {q}?", "link": "https://reddit.com/r/india", "source": "Reddit",
               "answers": [{"snippet": "Most people here recommend checking offline prices before buying online."}]}]
    return {"organic_results": organic, "discussions_and_forums": forums}


def _scholar(q: str) -> dict:
    r = _rng("sch", q)
    topics = ["A survey of", "Optimisation methods for", "Deep learning approaches to", "Challenges and open problems in",
              "A low-cost framework for", "Field study of"]
    return {"organic_results": [{
        "position": i + 1, "title": f"{t} {q}", "link": f"https://scholar.example.org/{i}",
        "snippet": f"Demo abstract: this paper studies {q} and reports limitations around cost, scalability and data.",
        "publication_info": {"summary": f"A Author, B Author - {r.randint(2018, 2026)} - IEEE Access"},
        "inline_links": {"cited_by": {"total": r.randint(3, 900)}}} for i, t in enumerate(topics)]}


def _youtube(q: str) -> dict:
    r = _rng("yt", q)
    parts = ["Full Course for Beginners", "in 100 Seconds", "Crash Course", "Tutorial — Hands-on Project",
             "Explained Simply", "Advanced Concepts", "Best Practices", "Interview Questions"]
    channels = ["freeCodeCamp.org", "Fireship", "TechWorld with Nana", "Traversy Media", "Programming with Mosh",
                "NetworkChuck", "Kunal Kushwaha", "Hitesh Choudhary"]
    topic = re.sub(r"\b(learn|learning|tutorial|how to|what should i watch|i'm trying to)\b", "", q, flags=re.I).strip() or q
    out = []
    for i, p in enumerate(parts):
        mins = r.choice([2, 12, 25, 48, 75, 140, 240])
        out.append({"position_on_page": i + 1, "title": f"{topic.title()} {p}",
                    "link": f"https://www.youtube.com/watch?v=demo{i}{abs(hash(q)) % 10000}",
                    "channel": {"name": channels[i % len(channels)], "verified": True},
                    "published_date": f"{r.randint(1, 30)} months ago", "views": r.randint(20_000, 4_000_000),
                    "length": f"{mins // 60}:{mins % 60:02d}:00" if mins >= 60 else f"{mins}:00",
                    "description": f"Demo video covering {topic} — {p.lower()}."})
    return {"video_results": out}


def _lens(url: str) -> dict:
    name, price, *_ = CATALOG["shoe"][-1]
    r = _rng("lens", url)
    matches = []
    for i, s in enumerate(["Amazon.in", "Myntra", "Nike.com", "Flipkart", "Ajio"]):
        p = int(price * r.uniform(0.85, 1.1))
        matches.append({"position": i + 1, "title": f"{name} - {s}", "link": f"https://example.com/lens/{i}",
                        "source": s, "price": {"value": _fmt_inr(p), "extracted_value": p, "currency": "₹"}})
    return {"visual_matches": matches, "knowledge_graph": [{"title": name}]}


def _flights(params: dict) -> dict:
    r = _rng("fl", params.get("departure_id"), params.get("arrival_id"), params.get("outbound_date"))
    airlines = ["IndiGo", "Air India", "Akasa Air", "Air India Express", "SpiceJet"]
    date = params.get("outbound_date") or datetime.now().strftime("%Y-%m-%d")
    flights = []
    for i, a in enumerate(airlines):
        dep_h = r.choice([6, 7, 9, 12, 15, 18, 21])
        dur = r.choice([55, 60, 65, 70, 150])
        dep = datetime.fromisoformat(date) + timedelta(hours=dep_h, minutes=r.choice([0, 15, 30, 45]))
        arr = dep + timedelta(minutes=dur)
        flights.append({"flights": [{"airline": a, "flight_number": f"{a[:2].upper()} {r.randint(100, 999)}",
                                     "departure_airport": {"id": params.get("departure_id"), "time": dep.strftime("%Y-%m-%d %H:%M")},
                                     "arrival_airport": {"id": params.get("arrival_id"), "time": arr.strftime("%Y-%m-%d %H:%M")},
                                     "duration": dur}],
                        "total_duration": dur, "price": r.randint(2400, 6800), "type": "One way"})
    return {"best_flights": flights[:2], "other_flights": flights[2:]}


def _hotels(q: str, params: dict | None = None) -> dict:
    r = _rng("ht", q)
    names = ["Treebo Trend", "FabHotel Prime", "Lemon Tree Hotel", "Ginger Hotel", "The Residency", "Zostel"]
    center = next((ll for n, ll in DEMO_DESTINATIONS.items() if n.lower() in q.lower()), None)
    props = []
    for n in names:
        p = {"name": f"{n} {q.split()[-1].title() if q.split() else ''}",
             "rate_per_night": {"lowest": _fmt_inr(v := r.randint(900, 6500)), "extracted_lowest": v},
             "overall_rating": round(r.uniform(3.5, 4.7), 1), "reviews": r.randint(50, 4000),
             "link": "https://example.com/hotel", "property_token": f"demo-{n}"}
        if center:
            p["gps_coordinates"] = {"latitude": center[0] + r.uniform(-0.02, 0.02),
                                    "longitude": center[1] + r.uniform(-0.02, 0.02)}
        props.append(p)
    return {"properties": props, "search_parameters": {k: (params or {}).get(k) for k in ("check_in_date", "check_out_date")}}


def _airbnb(q: str) -> dict:
    r = _rng("ab", q)
    return {"organic_results": [{"position": i + 1, "title": f"{k} in {q.title()}", "link": "https://example.com/rental",
                                 "extracted_price": r.randint(2500, 12000), "price_qualifier": "for 2 nights",
                                 "rating": round(r.uniform(4.2, 4.95), 2), "reviews": r.randint(5, 300)}
                                for i, k in enumerate(["Cottage", "Room", "Homestay", "Villa"])]}


def _tripadvisor(q: str, ssrc: str | None) -> dict:
    r = _rng("ta", q, ssrc)
    pools = {"A": ["Botanical Garden", "View Point", "Lake Boating", "Heritage Walk", "Waterfalls", "Old Market",
                   "Sunset Point", "Museum"],
             "r": ["Local Kitchen", "Cafe des Arts", "Hill Top Dhaba", "Spice Route Restaurant"],
             "h": ["Heritage Inn", "Backpacker Hostel", "Lakeview Resort"]}
    kind = {"A": "ATTRACTION", "r": "RESTAURANT", "h": "ACCOMMODATION"}.get(ssrc or "", "ATTRACTION")
    place = q.split(",")[0].title()
    return {"places": [{"position": i + 1, "title": f"{n}, {place}", "place_type": kind,
                        "link": "https://www.tripadvisor.com/demo", "description": f"Demo listing: {n} in {place}.",
                        "location": place} for i, n in enumerate(r.sample(pools.get(ssrc or "", pools["A"]), 4))]}


def _events(q: str) -> dict:
    r = _rng("ev", q)
    return {"events_results": [{"title": f"{t} — {q.title()}", "date": {"when": f"Sat, {r.randint(10, 28)} Oct, 7 PM"},
                                "address": ["Demo Venue", "Chennai"], "link": "https://example.com/event",
                                "venue": {"name": "Demo Arena", "rating": 4.3, "reviews": 120},
                                "ticket_info": [{"source": "BookMyShow", "link": "https://example.com/tickets"}]}
                               for t in ["Live Music Night", "Stand-up Comedy", "Food Festival"]]}


def _finance(q: str) -> dict:
    r = _rng("fin", q)
    return {"summary": {"title": q.split(":")[0], "stock": q.split(":")[0], "exchange": (q.split(":") + ["NSE"])[1],
                        "extracted_price": round(r.uniform(100, 5000), 2), "currency": "INR",
                        "price_movement": {"percentage": round(r.uniform(-2, 2), 2), "value": round(r.uniform(-50, 50), 2),
                                           "movement": r.choice(["Up", "Down"])}, "date": "demo"}}


def _trends(q: str) -> dict:
    r = _rng("tr", q)
    terms = [t.strip() for t in q.split(",") if t.strip()] or [q]
    return {"interest_over_time": {"timeline_data": [
        {"date": f"Week {w + 1}", "values": [{"query": t, "extracted_value": r.randint(20, 100)} for t in terms]}
        for w in range(12)]}}


def _apps(q: str, store: str) -> dict:
    r = _rng(store, q)
    names = [f"{q.title()} Pro", f"Easy {q.title()}", f"{q.title()} Lite"]
    if store == "google_play":
        return {"organic_results": [{"items": [{"title": n, "link": "https://example.com/app", "product_id": n,
                                                "rating": round(r.uniform(3.8, 4.7), 1), "author": "Demo Labs",
                                                "downloads": "1M+"} for n in names]}]}
    return {"organic_results": [{"position": i + 1, "title": n, "id": i, "link": "https://example.com/app",
                                 "rating": [{"type": "All Times", "rating": round(r.uniform(3.8, 4.8), 1), "count": r.randint(100, 9000)}],
                                 "price": {"type": "Free"}, "developer": {"name": "Demo Labs"}} for i, n in enumerate(names)]}


def _ai_mode(q: str) -> dict:
    place = next((n for n in DEMO_DESTINATIONS if n.lower() in q.lower()), None)
    if place or "itinerary" in q.lower():
        place = place or "the destination"
        md = (f"A short trip to {place} works well by road or rail.\n\n"
              f"- By Train + Bus (Budget):\n  - Overnight train, then a local bus. Takes about 8 hours.\n"
              f"  - Cost: ₹400–₹700 (train) + ₹100–₹200 (bus).\n"
              f"- By Direct Bus (Cheapest):\n  - Overnight sleeper bus. Takes about 9–10 hours.\n  - Cost: ₹700–₹1,200 one way.\n"
              f"- By Cab:\n  - Private outstation cab, 8 hours.\n  - Cost: ₹7,000–₹10,000 one way.\n\n"
              f"Day 1: Arrive and settle in\n\n- Morning: Arrive in {place} and check in.\n- Evening: Walk around the lake.\n\n"
              f"Day 2: Sightseeing\n\n- Morning: View point and gardens.\n- Afternoon: Waterfalls.\n\n"
              f"Day 3: Head home\n\n- Morning: Local market.\n- Afternoon: Start the return journey.\n")
    else:
        md = (f"Here is a demo answer about {q}. [0]\n\n- First key point about {q}.\n- Second key point.\n\n"
              f"- By Train (Fastest):\n  - Takes about 5 hours.\n  - Ticket Price: ₹500–₹900.\n"
              f"- By Bus (Cheapest):\n  - Takes about 6–7 hours.\n  - Ticket Price: ₹350–₹800.\n")
    return {"reconstructed_markdown": md, "text_blocks": [{"type": "paragraph", "snippet": md[:200]}],
            "references": [{"index": 0, "title": f"Guide: {q}", "link": "https://example.com/guide", "source": "example.com",
                            "snippet": "Demo reference."}]}


def _directions(params: dict) -> dict:
    end = str(params.get("end_addr") or "")
    ll = next((v for n, v in DEMO_DESTINATIONS.items() if n.lower() in end.lower()), None)
    if not ll:
        return {"directions": []}
    km = math.dist((13.08, 80.27), ll) * 111 * 1.25
    return {"directions": [{"travel_mode": "Driving", "via": "NH demo", "distance": int(km * 1000),
                            "duration": int(km / 55 * 3600), "formatted_distance": f"{km:.0f} km"}]}


def _markets() -> dict:
    return {"markets": {"asia": [{"name": "NIFTY 50", "stock": "NIFTY_50:INDEXNSE", "price": "24,812.30",
                                  "price_movement": {"percentage": 0.42, "value": 103.5, "movement": "Up"}},
                                 {"name": "S&P BSE SENSEX", "stock": "SENSEX:INDEXBOM", "price": "81,240.10",
                                  "price_movement": {"percentage": 0.38, "value": 305.2, "movement": "Up"}}],
                        "currencies": [{"name": "USD / INR", "stock": "USD-INR", "price": "83.95",
                                        "price_movement": {"percentage": 0.05, "value": 0.04, "movement": "Up"}}]}}


def _trending() -> dict:
    return {"trending_searches": [{"query": q, "search_volume": v, "increase_percentage": p, "active": True,
                                   "categories": [{"id": 17, "name": c}], "trend_breakdown": [q.split()[0]]}
                                  for q, v, p, c in [("india vs australia", 500000, 1000, "Sports"),
                                                     ("gold rate today", 100000, 300, "Business"),
                                                     ("new phone launch", 50000, 200, "Technology")]]}


def _maps_reviews(params: dict) -> dict:
    r = _rng("rev", params.get("data_id") or params.get("place_id"))
    return {"place_info": {"title": "Demo Place", "rating": 4.3, "reviews": 812},
            "topics": [{"keyword": k, "mentions": r.randint(5, 80)} for k in ("taste", "service", "price")],
            "reviews": [{"user": {"name": f"Reviewer {i}"}, "rating": r.randint(3, 5), "date": f"{i + 1} weeks ago",
                         "snippet": t} for i, t in enumerate(["Great food and quick service.", "A bit crowded on weekends.",
                                                             "Good value for money."])]}


def _hotel_reviews() -> dict:
    return {"reviews": [{"user": {"name": "Guest"}, "source": "Google", "rating": 4, "best_rating": 5, "date": "2 weeks ago",
                         "snippet": "Clean rooms and helpful staff, close to the lake.",
                         "subratings": {"rooms": 4.2, "service": 4.5, "location": 4.8}}]}


def _travel_explore(params: dict) -> dict:
    return {"destinations": [{"name": n, "country": "India", "gps_coordinates": {"latitude": ll[0], "longitude": ll[1]},
                              "destination_airport": {"code": "XXX"}, "flight_price": p, "flight_duration": 90,
                              "number_of_stops": 0, "airline": "IndiGo", "start_date": params.get("outbound_date")}
                             for n, ll, p in [("Goa", (15.49, 73.83), 4200), ("Jaipur", (26.91, 75.79), 5600)]]}


def _images(q: str) -> dict:
    return {"images_results": [{"position": i + 1, "title": f"{q.title()} photo {i + 1}", "link": "https://example.com/img",
                                "source": "example.com", "thumbnail": "", "original": ""} for i in range(4)]}


def _jobs(q: str) -> dict:
    r = _rng("jobs", q)
    cos = ["Zoho", "Freshworks", "TCS", "Infosys", "Chargebee", "Swiggy"]
    return {"jobs_results": [{"title": f"{q.title()}", "company_name": c, "location": "Chennai, Tamil Nadu",
                              "via": "LinkedIn", "detected_extensions": {"posted_at": f"{r.randint(1, 20)} days ago"}}
                             for c in cos]}


def generate(engine: str, params: dict[str, Any], hints: dict[str, Any]) -> dict[str, Any]:
    q = str(params.get("q") or params.get("k") or params.get("_nkw") or params.get("search_query") or "")
    if engine == "google_shopping":
        return _shopping(q, hints)
    if engine == "amazon":
        return _amazon(q, hints)
    if engine == "ebay":
        return _ebay(q, hints)
    if engine == "google_maps":
        return _maps(q, params.get("ll"))
    if engine == "google_news":
        return _news(q)
    if engine in ("google_scholar", "google_patents"):
        return _scholar(q)
    if engine == "youtube":
        return _youtube(q)
    if engine == "google_lens":
        return _lens(str(params.get("url")))
    if engine == "google_flights":
        return _flights(params)
    if engine == "google_hotels":
        return _hotels(q, params)
    if engine == "airbnb":
        return _airbnb(q)
    if engine == "tripadvisor":
        return _tripadvisor(q, params.get("ssrc"))
    if engine == "google_events":
        return _events(q)
    if engine == "google_finance":
        return _finance(q)
    if engine == "google_trends":
        return _trends(q)
    if engine in ("google_play", "apple_app_store"):
        return _apps(str(params.get("term") or q), engine)
    if engine == "google_images":
        return _images(q)
    if engine == "google_ai_mode":
        return _ai_mode(q)
    if engine == "google_finance_markets":
        return _markets()
    if engine == "google_trends_trending_now":
        return _trending()
    if engine == "google_maps_reviews":
        return _maps_reviews(params)
    if engine == "google_hotels_reviews":
        return _hotel_reviews()
    if engine == "google_travel_explore":
        return _travel_explore(params)
    if engine == "bing_copilot":
        return {"header": f"Demo Copilot answer about {q}.", "text_blocks": [], "references": []}
    if engine == "google_maps_directions":
        return _directions(params)
    if engine == "google_jobs":
        return _jobs(q)
    return _google(q)
