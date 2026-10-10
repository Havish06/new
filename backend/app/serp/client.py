"""SerpApi HTTP client with a SQLite-backed response cache.

When no SERPAPI_KEY is set (or DEMO_MODE=true) responses come from `demo.py`, which emits
SerpApi-shaped JSON so every downstream component runs identically offline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from ..config import settings
from . import demo

log = logging.getLogger("decisionos.serp")

ENDPOINT = "https://serpapi.com/search.json"


class SearchError(RuntimeError):
    pass


def _cache_key(engine: str, params: dict[str, Any]) -> str:
    blob = json.dumps({"engine": engine, **params}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def search(engine: str, params: dict[str, Any], use_cache: bool = True) -> dict[str, Any]:
    # Keys starting with "__" are hints for the demo generator only; never sent to SerpApi.
    # (A single underscore is legitimate: eBay's query parameter is `_nkw`.)
    hints = {k: v for k, v in params.items() if k.startswith("__")}
    clean = {k: v for k, v in params.items() if not k.startswith("__") and v not in (None, "")}

    if not settings.use_live_search:
        data = demo.generate(engine, clean, hints)
        data.setdefault("search_metadata", {})["demo"] = True
        return data

    key = _cache_key(engine, clean)
    if use_cache:
        row = db.fetch_one("SELECT response, created_at FROM search_cache WHERE key=?", (key,))
        if row:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])
            if age < timedelta(seconds=settings.search_cache_ttl_s):
                cached = json.loads(row["response"])
                cached.setdefault("search_metadata", {})["cached"] = True
                return cached

    query = urllib.parse.urlencode({"engine": engine, "api_key": settings.serpapi_key, **clean})
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{ENDPOINT}?{query}", timeout=40) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")[:300]
            last_err = SearchError(f"{engine}: HTTP {exc.code} {body}")
            if exc.code in (400, 401, 403):
                raise last_err
        except Exception as exc:  # timeouts, DNS, etc.
            last_err = exc
        time.sleep(1.5 * (attempt + 1))
    else:
        raise SearchError(f"{engine}: {last_err}")

    if data.get("error") and not any(k.endswith("_results") for k in data):
        # SerpApi returns {"error": "Google hasn't returned any results"} for empty searches.
        log.info("SerpApi %s returned: %s", engine, data["error"])
    db.upsert("search_cache", {"key": key, "engine": engine, "response": json.dumps(data),
                               "created_at": db.now_iso()}, key="key")
    return data


def account() -> dict[str, Any] | None:
    """SerpApi Account API (free, doesn't use a search): plan and searches left this month."""
    if not settings.serpapi_key:
        return None
    try:
        url = "https://serpapi.com/account.json?" + urllib.parse.urlencode({"api_key": settings.serpapi_key})
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {k: data.get(k) for k in ("plan_name", "searches_per_month", "plan_searches_left", "extra_credits",
                                         "total_searches_left", "this_month_usage", "account_rate_limit_per_hour")}
    except Exception as exc:
        log.info("SerpApi account lookup failed: %s", exc)
        return None
