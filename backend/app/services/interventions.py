"""Intervention policy + notification delivery (doc §18, §24-26).

    intervention_score = urgency + relevance + confidence - annoyance - quiet_hours_penalty

Only interventions above the mode's threshold are delivered. Suppressed ones are still logged
with the reason, so the user can audit why DecisionOS stayed quiet.
"""
from __future__ import annotations

import json
import logging
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

from .. import db
from ..config import settings as cfg
from .user_settings import get_settings, in_quiet_hours

log = logging.getLogger("decisionos.interventions")

MODE_THRESHOLD = {"assistant": 0.9, "normal": 1.3, "quiet": 1.9, "focus": float("inf"), "sleep": float("inf")}
CRITICAL_URGENCY = 0.9


def _recent_delivered(minutes: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    return db.fetch_all("SELECT * FROM interventions WHERE status='delivered' AND created_at>=?", (since,))


def evaluate(urgency: float, relevance: float, confidence: float, title: str, s: dict | None = None,
             at: datetime | None = None) -> dict[str, Any]:
    s = s or get_settings()
    mode = s.get("mode", "normal")
    critical = urgency >= CRITICAL_URGENCY
    recent = _recent_delivered(60)
    annoyance = 0.25 * len(recent)
    dismissed_same = db.fetch_one(
        "SELECT COUNT(*) AS n FROM interventions WHERE title=? AND response='dismissed' AND created_at>=?",
        (title, (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()))["n"]
    annoyance += 0.6 * dismissed_same
    quiet = in_quiet_hours(at, s)
    allow_critical = (s.get("quiet_hours") or {}).get("allow_critical", True)
    quiet_penalty = 0.0 if not quiet or (critical and allow_critical) else 1.5
    score = urgency + relevance + confidence - annoyance - quiet_penalty
    threshold = MODE_THRESHOLD.get(mode, 1.3)
    if critical and allow_critical and mode in ("focus", "sleep", "quiet"):
        threshold = 1.6            # critical items may break through, still subject to annoyance
    deliver = score >= threshold
    if not deliver:
        if quiet and quiet_penalty:
            reason = "Quiet hours"
        elif mode in ("focus", "sleep") and not critical:
            reason = f"{mode.title()} mode"
        elif annoyance >= 0.6:
            reason = "Too many recent notifications"
        else:
            reason = f"Score {score:.2f} below {mode} threshold {threshold:.2f}"
    else:
        reason = "Delivered"
    return {"deliver": deliver, "score": round(score, 3), "reason": reason, "threshold": threshold,
            "components": {"urgency": urgency, "relevance": relevance, "confidence": confidence,
                           "annoyance": round(annoyance, 2), "quiet_penalty": quiet_penalty, "mode": mode,
                           "critical": critical}}


def create(event_type: str, title: str, message: str, urgency: float, relevance: float = 0.5,
           confidence: float = 0.8, actions: list[dict] | None = None, force: bool = False) -> dict:
    """force=True is for direct answers to the user's own actions (e.g. memory confirmation prompts)."""
    s = get_settings()
    ev = evaluate(urgency, relevance, confidence, title, s)
    deliver = ev["deliver"] or force
    row = {"id": db.new_id("int"), "event_type": event_type, "title": title, "message": message,
           "score": ev["score"], "components": ev["components"], "status": "delivered" if deliver else "suppressed",
           "reason": "Requested by you" if force and not ev["deliver"] else ev["reason"], "actions": actions or [],
           "seen": 0, "response": None, "created_at": db.now_iso()}
    db.insert("interventions", row)
    if deliver:
        _push_external(row, s)
    return row


def list_interventions(status: str | None = None, unseen: bool = False, limit: int = 50) -> list[dict]:
    sql, params = "SELECT * FROM interventions", []
    conds = []
    if status:
        conds.append("status=?")
        params.append(status)
    if unseen:
        conds.append("seen=0")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return db.fetch_all(sql, tuple(params))


def mark_seen(ids: list[str]) -> None:
    for i in ids:
        db.update("interventions", i, {"seen": 1})


# ------------------------------------------------------------------ external channels
def _push_external(row: dict, s: dict) -> None:
    n = s.get("notifications") or {}
    important = row["components"].get("urgency", 0) >= 0.7
    if n.get("email") and important and cfg.smtp_host and cfg.notify_email_to:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"DecisionOS: {row['title']}"
            msg["From"] = cfg.smtp_user or "decisionos@localhost"
            msg["To"] = cfg.notify_email_to
            msg.set_content(row["message"])
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                if cfg.smtp_user:
                    smtp.login(cfg.smtp_user, cfg.smtp_password)
                smtp.send_message(msg)
        except Exception as exc:
            log.warning("email notification failed: %s", exc)
    if n.get("telegram") and important and cfg.telegram_bot_token and cfg.telegram_chat_id:
        try:
            data = urllib.parse.urlencode({"chat_id": cfg.telegram_chat_id,
                                           "text": f"🔔 {row['title']}\n{row['message']}"}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
                                   data=data, timeout=15).read()
        except Exception as exc:
            log.warning("telegram notification failed: %s", exc)


def to_json(row: dict) -> str:
    return json.dumps(row, default=str)
