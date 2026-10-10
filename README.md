# DecisionOS

**Don't search. Decide. Act.** — DecisionOS turns *"What should I do?"* into a researched decision, an actionable plan, and timely follow-through.

```
QUESTION → RESEARCH → EVIDENCE → DECISION → PLAN → CALENDAR / TASKS / REMINDERS → MEMORY → FOLLOW-UP
```

It is built from the two design docs (`Documentation.md`, `API_Strategy.md`) and covers all four roadmap phases:

| Phase | What's in it |
|---|---|
| 1 · Decide | Natural-language goal → constraint extraction (Claude) → research plan → SerpApi capability router → evidence fusion with per-fact confidence → weighted scoring → explanation, "Why?", alternatives, **What if?** |
| 2 · Plan | Plan generator, tasks, context-aware reminders, calendar (built-in + `.ics` feed + optional Google Calendar sync) |
| 3 · Remember | Inspectable/editable memory, explicit "remember that…", inferred preferences that are only *proposed* and need your confirmation |
| 4 · Follow up | Opt-in desktop agent (active app, project, idle time only), idle detection, priority-ranked suggestions, quiet hours, modes, interruption score |

## Decision types

| You say | Type | Live sources (via semantic tools) |
|---|---|---|
| "Laptop for coding under ₹70K, lightweight" | product | Google Shopping + Amazon (+ eBay/Walmart outside India), web reviews |
| 📷 image + "what is this?" | visual | Google Lens → product identity → Shopping/Amazon price comparison |
| "Where should I repair my laptop?" | local | Google Maps (rating, reviews, distance, opening hours) |
| "Buy a USB drive, print my assignment, get passport photos, reach college by 4 PM, ₹1,000" | errands | Maps per stop → route ordering → timeline → total cost vs budget |
| "Chennai to Bangalore this weekend under ₹3,000" | travel | Google Flights + train/bus estimates from web results |
| "I'm learning Docker, what should I watch?" | video | YouTube → de-duplicated day-by-day learning path |
| "Project about EV charging — what problem should I work on?" | research | Google Scholar + Patents + News → landscape + scored directions |
| "Remind me to submit this tomorrow at 6 PM" | reminder | — |

## Project layout

```
decisionos/
├── backend/                 FastAPI + SQLite (stdlib-only engine)
│   ├── app/
│   │   ├── main.py          API gateway (all endpoints)
│   │   ├── llm.py           Claude API wrapper (every caller has a non-LLM fallback)
│   │   ├── serp/            SerpApi client + cache, semantic capabilities, offline demo data
│   │   ├── engine/          intent · orchestrator · evidence · decision · explain · errands · synthesis · planner
│   │   └── services/        tasks · calendar · memory · interventions · proactive loop · activity · metrics
│   └── tests/test_pipeline.py
├── frontend/                Next.js 14 + TypeScript + Tailwind
│   └── app/                 Today · Decide · Decision view · Tasks · Calendar · Inbox · Memory · Settings
└── workspace_agent/agent.py Local opt-in activity agent + desktop notifications (stdlib only)
```

## Setup

You need **Python 3.11+** and **Node.js 18+**.

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # macOS/Linux: cp .env.example .env
```

Edit `backend/.env`:

- `ANTHROPIC_API_KEY` — your Claude API key (console.anthropic.com). Without it the app still runs on heuristic fallbacks, but with weaker understanding and no train/bus estimates or research synthesis.
- `SERPAPI_KEY` — from serpapi.com. **Leave empty to run on built-in demo data** (labelled "demo data" in the UI) — useful for rehearsing without spending searches.

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
copy .env.local.example .env.local     # macOS/Linux: cp
npm run dev
```

Open http://localhost:3000 → **Settings** → set your name and your home/hostel location (and saved places like "college").

### 3. Workspace agent (optional, Phase 4)

1. In Settings → *Workspace awareness*, tick **Enable activity awareness**.
2. In another terminal: `python workspace_agent/agent.py`
3. Privacy check first if you like: `python workspace_agent/agent.py --once` prints exactly what would be sent.

Optional `workspace_agent/agent_config.json` maps project names to folders so idle suggestions can offer "Open in VS Code" (see `agent_config.example.json`). On Linux install `xdotool` and `xprintidle`.

### Tests

```bash
cd backend
python tests/test_pipeline.py      # or: python -m pytest -q
```

## Hackathon demo script (≈2 min)

1. **Today** → type: *"I have an interview tomorrow at 10 AM. I need formal shoes, I need to print my resume, and I need to reach the office by 9:30 AM. I have ₹3,000."*
2. Watch the agent loop run → errand plan: total cost vs budget, stops, distance, timeline.
3. **What if?** → "What if I only want places rated 4.5+?" — re-plans instantly.
4. **Plan → Add plan** → tasks, calendar events and reminders appear (Calendar page, `.ics` download).
5. New decision: *"Laptop for coding under ₹70,000, lightweight"* → open **Why?** (priorities, eliminated, score table, what could change) and **Evidence** (every price by source + every search run). Click "Try it" on a *what could change* row.
6. **Today → Simulate 20 min idle** → a toast: *"You've been idle… 'Print resume' is due at… Bata Store closes at 9 PM and is 1.6 km away."*
7. **Inbox** shows nudges that were *held back* (focus mode / quiet hours) with their interruption score.
8. Accept 3 cheap options → DecisionOS asks *"You seem to prioritise the lowest price. Should I remember this?"* (never saved silently).

## How it maps to the design docs

- **Capability-based router** (API_Strategy §9–11): the LLM never sees engine names; `serp/capabilities.py` exposes `search_web`, `research_product`, `find_local_places`, `find_route`, `research_travel`, `research_hotels`, `research_news`, `research_academic`, `research_jobs`, `research_video`, `analyze_image`.
- **Research plan** (§12): `orchestrator.RESEARCH_TEMPLATES`, logged per decision and shown in the Evidence tab.
- **Evidence fusion & confidence** (§13–14): `engine/evidence.py` clusters listings across sources, keeps every value with its source, flags price disagreement ("Don't buy the Amazon listing yet…").
- **Decision engine** (Doc §11): deterministic weighted scoring in `engine/decision.py`; Claude only scores *soft* criteria (e.g. "coding performance") and writes explanations — it never picks the winner.
- **Intervention policy** (Doc §25): `score = urgency + relevance + confidence − annoyance − quiet_penalty`, thresholds per mode, critical override, full audit trail in Inbox.
- **Event-driven proactive loop** (Doc §40–41): no LLM calls in the loop; events `TASK_DUE_SOON`, `TASK_OVERDUE`, `REMINDER_DUE`, `CALENDAR_EVENT_APPROACHING`, `USER_IDLE`, `USER_RETURNED`, `PLANNED_TASK_NOT_STARTED`, `BREAK_SUGGESTED`, `SEARCH_RESULT_EXPIRED`, `PROJECT_ABANDONED`, `DEADLINE_CHANGED`, `QUIET_HOURS_STARTED/ENDED`.
- **Success metrics** (Doc §47): `/api/metrics`, shown as *Impact* on the Today page.

## Notes & limits

- **User stays in control**: nothing is purchased, sent or booked automatically; plans are steps for you.
- **Storage**: SQLite (`backend/decisionos.db`) so it runs on one laptop with zero setup; the schema mirrors the doc's entities and moves to PostgreSQL mechanically. The search cache replaces Redis for the same reason.
- **Google Lens needs a public image URL.** Paste an image link, or expose the backend (e.g. `ngrok http 8000`) and set `PUBLIC_BACKEND_URL` so uploads are reachable.
- **Google Calendar sync** is optional: create an OAuth "Web application" client, add redirect URI `{PUBLIC_BACKEND_URL}/api/calendar/google/callback`, fill `GOOGLE_CLIENT_ID/SECRET`. Without it, use the built-in calendar and `.ics` export.
- Train/bus options are *estimates* extracted from search snippets and labelled as such.
- Single-user by design (local hackathon build); add Supabase auth for multi-user.
