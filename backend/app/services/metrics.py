"""Success metrics (doc §47)."""
from __future__ import annotations

from typing import Any

from .. import db

# Rough count of manual steps a user performs per searched source / plan step (tabs opened,
# comparisons, copying into calendar, setting alarms). Used for the "steps removed" estimate.
STEPS_PER_SEARCH = 3
STEPS_PER_COMMITTED_TASK = 2


def _n(sql: str, params: tuple = ()) -> int:
    return db.fetch_one(sql, params)["n"]


def summary() -> dict[str, Any]:
    decisions = _n("SELECT COUNT(*) AS n FROM decisions")
    ready_or_after = _n("SELECT COUNT(*) AS n FROM decisions WHERE status IN ('ready','accepted','planned')")
    accepted = _n("SELECT COUNT(*) AS n FROM decisions WHERE status IN ('accepted','planned')")
    overridden = _n("SELECT COUNT(*) AS n FROM decisions WHERE json_extract(result,'$.user_choice') IS NOT NULL")
    tasks_total = _n("SELECT COUNT(*) AS n FROM tasks")
    tasks_done = _n("SELECT COUNT(*) AS n FROM tasks WHERE status='done'")
    plan_tasks = _n("SELECT COUNT(*) AS n FROM tasks WHERE source_decision IS NOT NULL")
    plan_done = _n("SELECT COUNT(*) AS n FROM tasks WHERE source_decision IS NOT NULL AND status='done'")
    rem_acted = _n("SELECT COUNT(*) AS n FROM reminders WHERE status='acted'")
    rem_fired = _n("SELECT COUNT(*) AS n FROM reminders WHERE status IN ('fired','acted','dismissed')")
    delivered = _n("SELECT COUNT(*) AS n FROM interventions WHERE status='delivered'")
    suppressed = _n("SELECT COUNT(*) AS n FROM interventions WHERE status='suppressed'")
    engaged = _n("SELECT COUNT(*) AS n FROM interventions WHERE response='acted'")
    dismissed = _n("SELECT COUNT(*) AS n FROM interventions WHERE response='dismissed'")
    searches = 0
    for r in db.fetch_all("SELECT research FROM decisions"):
        searches += len((r["research"] or {}).get("calls") or [])
    events = _n("SELECT COUNT(*) AS n FROM calendar_events")

    def pct(a: int, b: int) -> float | None:
        return round(100 * a / b, 1) if b else None

    return {
        "decisions": decisions,
        "decision_acceptance_pct": pct(accepted, ready_or_after),
        "recommendation_overrides": overridden,
        "plan_completion_pct": pct(plan_done, plan_tasks),
        "task_completion_pct": pct(tasks_done, tasks_total),
        "reminder_usefulness_pct": pct(rem_acted, rem_fired),
        "interventions_delivered": delivered, "interventions_suppressed": suppressed,
        "intervention_engagement_pct": pct(engaged, engaged + dismissed),
        "avg_searches_per_decision": round(searches / decisions, 1) if decisions else None,
        "steps_removed_estimate": searches * STEPS_PER_SEARCH + plan_tasks * STEPS_PER_COMMITTED_TASK + events,
    }
