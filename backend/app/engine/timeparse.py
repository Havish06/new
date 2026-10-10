"""Small natural-language time parser used when the LLM is unavailable (and to validate it).

Handles: today/tonight/tomorrow/day after tomorrow, weekdays ("on Friday", "before Saturday"),
"at 6 pm", "6:30pm", "10 AM", "18:00", "in 30 minutes", "in 2 hours", "noon", parts of day
("tomorrow evening"), and "this week"/"this weekend".
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
PARTS = {"morning": (9, 0), "noon": (12, 0), "afternoon": (15, 0), "evening": (19, 0),
         "tonight": (20, 0), "night": (21, 0)}

_TIME_RE = re.compile(r"\b(?:at\s+|by\s+|before\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b", re.I)
_24H_RE = re.compile(r"\b(?:at|by|before)\s+([01]?\d|2[0-3]):([0-5]\d)\b", re.I)
_REL_RE = re.compile(r"\bin\s+(\d+|an?|half an)\s*(minute|min|hour|hr|day|week)s?\b", re.I)


def _clock(text: str) -> tuple[int, int] | None:
    m = _TIME_RE.search(text)
    if m:
        h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower().replace(".", "")
        if h == 12:
            h = 0
        if ap == "pm":
            h += 12
        return h % 24, mins
    m = _24H_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def all_clock_times(text: str) -> list[tuple[int, int, str]]:
    """Every explicit clock time in the text with the 40 chars preceding it (for context)."""
    out = []
    for m in _TIME_RE.finditer(text):
        h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower().replace(".", "")
        h = (0 if h == 12 else h) + (12 if ap == "pm" else 0)
        out.append((h % 24, mins, text[max(0, m.start() - 40):m.start()].lower()))
    return out


def _day_offset(text: str, now: datetime) -> int | None:
    t = text.lower()
    if "day after tomorrow" in t:
        return 2
    if "tomorrow" in t or "tmrw" in t or "tmr" in t:
        return 1
    if any(w in t for w in ("today", "tonight", "this evening", "this afternoon", "this morning")):
        return 0
    for i, d in enumerate(WEEKDAYS):
        if re.search(rf"\b{d}\b", t):
            delta = (i - now.weekday()) % 7
            return delta if delta else 7 if "next" in t else 0
    return None


def parse_when(text: str, now: datetime) -> datetime | None:
    """Return a timezone-aware datetime (same tz as `now`) or None."""
    t = text.lower()
    rel = _REL_RE.search(t)
    if rel:
        qty = rel.group(1)
        n = 1 if qty in ("a", "an") else 0.5 if qty == "half an" else int(qty)
        unit = rel.group(2)
        delta = {"minute": timedelta(minutes=n), "min": timedelta(minutes=n), "hour": timedelta(hours=n),
                 "hr": timedelta(hours=n), "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
        return (now + delta).replace(second=0, microsecond=0)

    day = _day_offset(t, now)
    clock = _clock(t)
    if clock is None:
        for word, hm in PARTS.items():
            if re.search(rf"\b{word}\b", t):
                clock = hm
                break
    if day is None and clock is None:
        if "this weekend" in t or "weekend" in t:
            day = (5 - now.weekday()) % 7
            clock = (10, 0)
        elif "this week" in t:
            day = (6 - now.weekday()) % 7
            clock = (18, 0)
        else:
            return None
    if day is None:
        day = 0
    h, m = clock if clock else (9, 0)
    out = (now + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
    if day == 0 and out < now and clock and not re.search(r"\btoday\b", t):
        out += timedelta(days=1)   # "at 6 pm" said at 7 pm means tomorrow
    return out
