"""Memory Engine (doc §14-15, §30).

- Explicit memories ("remember that ...") are stored immediately.
- Inferred preferences are NEVER stored silently: repeated behaviour creates a *proposed* memory and
  an intervention asking the user to confirm. Only confirmed memories influence decisions.
- Every memory is inspectable, editable and deletable.
"""
from __future__ import annotations

import re
from typing import Any

from .. import db

INFERENCE_THRESHOLD = 3
SIGNAL_TEXT = {
    "chose_local": ("preference", "Prefers buying from local stores"),
    "chose_online": ("preference", "Prefers buying online"),
    "chose_cheapest": ("preference", "Usually prioritises the lowest price (budget-conscious)"),
    "chose_top_rated": ("preference", "Prefers highly rated options even if they cost more"),
    "chose_closest": ("preference", "Prefers the closest option for local services"),
}


def _kind_for(text: str) -> str:
    t = text.lower()
    if re.search(r"\bprefer|rather|always buy|never buy|budget\b", t):
        return "preference"
    if re.search(r"\bproject|working on|building\b", t):
        return "project"
    if re.search(r"\busually|every (day|morning|evening|night|week)|habit\b", t):
        return "habit"
    if re.search(r"\b(like|love|enjoy|hobby|interested in)\b", t):
        return "interest"
    return "fact"


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in {"that", "the", "and", "remember"}}


def _similar(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) / (len(ta | tb) or 1)


def list_memories(status: str | None = None) -> list[dict[str, Any]]:
    if status:
        return db.fetch_all("SELECT * FROM memories WHERE status=? ORDER BY updated_at DESC", (status,))
    return db.fetch_all("SELECT * FROM memories WHERE status!='rejected' ORDER BY kind, updated_at DESC")


def add_memory(content: str, kind: str | None = None, source: str = "explicit", status: str = "active",
               meta: dict | None = None) -> dict[str, Any]:
    content = content.strip().rstrip(".")
    if content.lower().startswith("i "):
        content = content[2:].strip().capitalize()
    for m in list_memories():
        if _similar(m["content"], content) > 0.7:
            db.update("memories", m["id"], {"content": content, "status": "active" if status == "active" else m["status"],
                                            "updated_at": db.now_iso()})
            return {**m, "content": content}
    row = {"id": db.new_id("mem"), "kind": kind or _kind_for(content), "content": content, "source": source,
           "status": status, "meta": meta or {}, "created_at": db.now_iso(), "updated_at": db.now_iso()}
    db.insert("memories", row)
    return row


def edit_memory(mem_id: str, patch: dict[str, Any]) -> dict | None:
    allowed = {k: v for k, v in patch.items() if k in ("content", "kind", "status")}
    allowed["updated_at"] = db.now_iso()
    db.update("memories", mem_id, allowed)
    return db.fetch_one("SELECT * FROM memories WHERE id=?", (mem_id,))


def delete_memory(mem_id: str) -> None:
    db.delete("memories", mem_id)


def forget(text: str) -> dict | None:
    best, best_s = None, 0.0
    for m in list_memories():
        s = _similar(m["content"], text)
        if s > best_s:
            best, best_s = m, s
    if best and best_s >= 0.25:
        delete_memory(best["id"])
        return best
    return None


def active_preferences() -> list[str]:
    return [m["content"] for m in db.fetch_all(
        "SELECT content FROM memories WHERE status='active' AND kind IN ('preference','habit','fact') "
        "ORDER BY updated_at DESC LIMIT 20")]


def record_signal(signal: str, decision_id: str | None) -> dict | None:
    """Record behaviour; once a pattern repeats, PROPOSE (never auto-save) a memory."""
    db.insert("signals", {"id": db.new_id("sig"), "signal": signal, "decision_id": decision_id,
                          "created_at": db.now_iso()})
    if signal not in SIGNAL_TEXT:
        return None
    n = db.fetch_one("SELECT COUNT(*) AS n FROM signals WHERE signal=?", (signal,))["n"]
    if n < INFERENCE_THRESHOLD:
        return None
    kind, text = SIGNAL_TEXT[signal]
    for m in db.fetch_all("SELECT * FROM memories"):
        if _similar(m["content"], text) > 0.7:
            return None            # already active, proposed or rejected — don't nag
    return add_memory(text, kind=kind, source="inferred", status="proposed", meta={"signal": signal, "count": n})
