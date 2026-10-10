# DecisionOS

**Don't just search. Make informed decisions. Take action.**

DecisionOS is an AI-powered decision-making and personal productivity platform that transforms everyday questions into research-backed decisions, practical action plans, and timely follow-ups. Instead of making users search across multiple platforms and manually organize the results, DecisionOS brings research, evidence, planning, reminders, and personal memory into a single workflow.

Its core pipeline is:

**QUESTION → RESEARCH → EVIDENCE → DECISION → PLAN → CALENDAR / TASKS / REMINDERS → MEMORY → FOLLOW-UP**

## 1. Core Roadmap

DecisionOS is built around four interconnected phases, combining the requirements defined in `Documentation.md` and `API_Strategy.md`.

| Phase | Description |
|---|---|
| **Phase 1: Decide** | Converts natural-language queries into structured goals, researches relevant sources, evaluates evidence, compares alternatives, and generates explainable recommendations. |
| **Phase 2: Plan** | Converts decisions into actionable tasks, schedules, calendar events, and context-aware reminders. |
| **Phase 3: Remember** | Maintains an inspectable, editable memory of user preferences and explicitly saved information, with confirmation required before inferred preferences are stored. |
| **Phase 4: Follow Up** | Provides optional desktop awareness, detects idle periods, prioritizes useful suggestions, and respects quiet hours, focus modes, and user-defined interruption preferences. |

### Phase 1: Decide

The user describes a goal in natural language. Claude helps extract the objective, constraints, priorities, and preferences. DecisionOS then creates a research plan, routes queries to appropriate SerpApi capabilities, combines evidence from multiple sources, and assigns confidence levels to individual facts.

A deterministic, weighted scoring engine evaluates the available options. The final result includes:

- A recommended decision with a clear explanation.
- Supporting evidence, source references, and confidence indicators.
- A **Why?** view explaining priorities, scores, and eliminated alternatives.
- A **What if?** feature that recalculates recommendations when the user changes a constraint.
- An evidence trail showing which sources were consulted and what information was retrieved.

Claude assists with interpretation and explanations, but the deterministic scoring engine remains responsible for selecting the winner.

### Phase 2: Plan

Once a decision is made, DecisionOS turns it into a practical execution plan. Users can organize tasks, set deadlines, schedule calendar events, and receive context-aware reminders.

The calendar supports built-in scheduling and `.ics` export, with optional Google Calendar synchronization. Plans remain under the user's control; DecisionOS does not automatically purchase products, send messages, or book services.

### Phase 3: Remember

DecisionOS provides transparent, user-controlled memory. Users can explicitly save information, inspect existing memories, and edit or delete stored preferences.

The system may also identify recurring preferences from user interactions. However, inferred preferences are presented as suggestions and require the user's approval before being saved.

### Phase 4: Follow Up

An optional local desktop agent helps DecisionOS provide relevant suggestions at appropriate times. With the user's permission, it can monitor limited contextual signals such as the active application, current project, and idle duration.

Its event-driven system prioritizes suggestions using urgency, relevance, confidence, potential annoyance, and quiet-hour penalties. Focus modes, configurable quiet hours, interruption thresholds, and an audit trail help prevent unnecessary interruptions.

The agent does not make LLM calls inside its proactive event loop.

## 2. Supported Decision Types

DecisionOS uses a capability-based research architecture to select appropriate information sources for different kinds of requests.

| Decision type | Example user request | Research capabilities |
|---|---|---|
| **Product discovery** | "Find a lightweight laptop for coding under ₹70,000." | Google Shopping, Amazon, and web-based reviews; eBay and Walmart where supported outside India. |
| **Visual identification** | Upload an image and ask, "What is this?" | Google Lens identification followed by product searches and price comparisons. |
| **Local services** | "Where should I get my laptop repaired?" | Google Maps information, ratings, reviews, distance, and opening hours. |
| **Errand planning** | "Buy a USB drive, print my assignment, and get passport photos within ₹1,000." | Local place discovery, route ordering, time estimation, and budget comparison. |
| **Travel planning** | "Plan a Chennai-to-Bengaluru trip this weekend under ₹3,000." | Google Flights and web research for train and bus estimates. |
| **Video learning** | "I'm learning Docker. What should I watch?" | YouTube discovery, duplicate removal, and a day-by-day learning sequence. |
| **Research discovery** | "What problem should I solve for a project about EV charging?" | Google Scholar, patents, and news research, followed by a comparison of potential project directions. |
| **Reminders** | "Remind me to submit this tomorrow at 6 PM." | Reminder creation using the specified deadline. |

## 3. Technical Architecture

DecisionOS uses a lightweight backend, a modern web frontend, and an optional local desktop agent.

```text
decisionos/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── llm.py
│   │   ├── serp/
│   │   ├── engine/
│   │   └── services/
│   └── tests/
│       └── test_pipeline.py
├── frontend/
│   └── app/
└── workspace_agent/
    └── agent.py
```

### Backend

**Technology:** FastAPI, Python, SQLite, and the standard library wherever practical.

- `main.py`: API gateway that exposes application endpoints.
- `llm.py`: Claude API integration with non-LLM fallbacks for every caller.
- `serp/`: SerpApi client, caching, semantic capability routing, and offline demonstration data.
- `engine/`: Intent extraction, research orchestration, evidence fusion, decision scoring, explanations, errand planning, synthesis, and plan generation.
- `services/`: Task management, calendar operations, memory, intervention policies, proactive events, activity tracking, and metrics.
- `tests/test_pipeline.py`: Pipeline testing and validation.

### Frontend

**Technology:** Next.js 14, TypeScript, and Tailwind CSS.

The interface is organized into the following sections:

- **Today:** Daily overview, upcoming tasks, reminders, and decision activity.
- **Decide:** Natural-language input for creating a new decision.
- **Decision View:** Recommendations, alternatives, explanations, evidence, and what-if analysis.
- **Tasks:** Action items and deadlines.
- **Calendar:** Scheduled events and calendar integration.
- **Inbox:** Suggestions, notifications, and held-back interventions.
- **Memory:** Saved information and user-approved preferences.
- **Settings:** Personal details, saved locations, workspace awareness, and application preferences.

### Workspace Agent

The optional desktop agent runs locally and uses standard-library functionality where possible. It supports activity awareness, idle detection, and desktop notifications.

Users can preview the information that would be transmitted by running the agent in one-shot mode before enabling continuous monitoring.

An optional configuration file maps project names to local folders, allowing suggestions to include actions such as opening a project in VS Code.

## 4. Setup and Execution

### Prerequisites

- Python 3.11 or later.
- Node.js 18 or later.
- An Anthropic API key and a SerpApi key for their respective live capabilities.

Both integrations are optional for basic local execution, subject to the functionality available in the fallback implementations.

### Backend setup

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment.

Windows:

```powershell
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies and configure the environment:

```bash
pip install -r requirements.txt
copy .env.example .env
```

On macOS/Linux, replace the final command with `cp .env.example .env`.

Configure `backend/.env`:

- `ANTHROPIC_API_KEY`: Enables Claude-based interpretation, explanations, and research synthesis where implemented.
- `SERPAPI_KEY`: Enables live SerpApi research capabilities. Leave it empty to use built-in demonstration data.

Start the backend:

```bash
uvicorn app.main:app --reload --port 8000
```

API documentation will be available at `http://localhost:8000/docs`.

### Frontend setup

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

On macOS/Linux, use `cp` instead of `copy`.

Open `http://localhost:3000`, navigate to Settings, and configure your name, home or hostel location, and saved places such as your college.

### Optional workspace agent

1. Enable **Workspace Awareness** in Settings.
2. Run the agent from a separate terminal:

   ```bash
   python workspace_agent/agent.py
   ```

3. To inspect the information it would send before continuous operation, run:

   ```bash
   python workspace_agent/agent.py --once
   ```

On Linux, additional utilities such as `xdotool` and `xprintidle` may be required.

### Testing

Run the pipeline tests from the backend directory:

```bash
python tests/test_pipeline.py
```

Alternatively:

```bash
python -m pytest -q
```

## 5. Hackathon Demonstration

The demonstration showcases how DecisionOS connects research, decision-making, planning, and proactive assistance in a single experience.

**Step 1: Enter a real-world goal**

On the Today page, enter:

"I'm attending an interview tomorrow at 10 AM. I need formal shoes, I need to print my resume, and I need to reach the office by 9:30 AM. I have ₹3,000."

**Step 2: Generate an errand plan**

DecisionOS researches relevant locations, estimates expenses, organizes stops, and produces a proposed timeline. The results are compared against the available budget.

**Step 3: Change the constraints**

Use **What if?** to add a condition such as "Only include places rated 4.5 or higher." DecisionOS recalculates the plan using the updated requirements.

**Step 4: Convert the decision into actions**

Select **Plan → Add Plan** to create tasks, calendar events, and reminders. The resulting schedule is available in the Calendar section, with `.ics` export for external calendar applications.

**Step 5: Explore a product decision**

Submit a second request:

"Find a lightweight laptop for coding under ₹70,000."

Open **Why?** to inspect the recommendation, priorities, scores, eliminated options, and factors that could change the outcome. Open **Evidence** to review retrieved information and source-level price comparisons.

Select **Try it** on a relevant what-could-change suggestion to explore an alternative decision.

**Step 6: Demonstrate proactive assistance**

Use **Simulate 20 min idle** on the Today page to demonstrate how an idle event can trigger a relevant suggestion, such as reminding the user to print a resume or highlighting a nearby store's closing time.

**Step 7: Demonstrate interruption management**

Open the Inbox to review suggestions that were held back by focus mode or quiet hours, along with their interruption scores.

**Step 8: Demonstrate transparent memory**

Accept several low-cost recommendations. If the system identifies a recurring preference for lower prices, it proposes saving that preference and asks for confirmation before adding it to memory.

This final step demonstrates that DecisionOS adapts to the user without silently storing inferred preferences.

## 6. Design Principles and Engineering Decisions

### Capability-based research routing

As defined in `API_Strategy.md`, the LLM works with semantic capabilities rather than internal engine names.

The router exposes capabilities such as:

- `search_web`
- `research_product`
- `find_local_places`
- `find_route`
- `research_travel`
- `research_hotels`
- `research_news`
- `research_academic`
- `research_jobs`
- `research_video`
- `analyze_image`

This separates the user's intent from the implementation details of individual search providers.

### Research planning and traceability

The orchestrator maintains reusable research templates and records the searches associated with each decision. Users can inspect the research process through the Evidence interface.

### Evidence fusion and confidence

The evidence engine groups potentially duplicate listings across sources while preserving source-specific values. It tracks individual facts, identifies conflicting information, and highlights discrepancies that could affect a decision.

For example, inconsistent prices across listings can trigger a warning rather than an unsupported recommendation to purchase immediately.

### Deterministic decision scoring

The decision engine applies weighted scoring to evaluate options against user-defined constraints and priorities. Claude can help assess qualitative criteria, such as coding performance, and explain the results, but it does not independently determine the final winner.

### Controlled interventions

The intervention policy evaluates whether a suggestion should be presented based on:

`score = urgency + relevance + confidence − annoyance − quiet_penalty`

Mode-specific thresholds, quiet hours, critical-event overrides, and an audit trail help determine which suggestions are shown, delayed, or withheld.

### Event-driven proactive loop

The proactive loop responds to application events without making LLM calls inside the loop. Supported event categories include:

- Task due soon or overdue.
- Reminder due.
- Calendar event approaching.
- User idle or returned.
- Planned task not started.
- Break suggestion.
- Search result expired.
- Project abandoned.
- Deadline changed.
- Quiet hours started or ended.

This design helps keep proactive behavior predictable and reduces unnecessary model usage.

### Measurable impact

The backend exposes `/api/metrics`, allowing the Today page to present the application's impact using the success metrics defined in `Documentation.md`.

## 7. Storage, Integrations, and Limitations

### Storage

DecisionOS uses SQLite for its single-user local deployment. This avoids the need for a separate database server and keeps setup simple.

The database schema is designed to support a future migration to PostgreSQL. The search cache provides lightweight caching without requiring Redis.

### API keys and fallback behavior

Without an Anthropic API key, the application uses heuristic fallbacks, although natural-language understanding and research synthesis may be less capable.

Without a SerpApi key, built-in demonstration data allows the application to run through sample workflows. Demonstration data must remain clearly labelled so users do not mistake it for live research.

### Image identification

Google Lens integration requires an image that the external service can access through a public URL. Users can supply an image link or configure a publicly reachable backend using a service such as ngrok and set `PUBLIC_BACKEND_URL` accordingly.

### Google Calendar

Google Calendar synchronization is optional. It requires an OAuth web application client, a configured redirect URI, and the corresponding client ID and secret.

Without this integration, the built-in calendar and `.ics` export remain available.

### Travel estimates

Train and bus options may be extracted from web search snippets. These results are estimates, not confirmed fares, schedules, or bookings, and must be presented accordingly.

### User and privacy boundaries

The current build is designed for a single user on a local machine. Multi-user authentication, such as Supabase Auth, can be introduced later.

Workspace awareness is opt-in, and the user remains in control of decisions and actions. No purchase, booking, or external communication is performed automatically.

## 8. Overall Vision

DecisionOS aims to move beyond conventional search and productivity applications by connecting information discovery with actual decision-making and follow-through.

Its value lies in the complete workflow: understanding what the user wants, researching credible evidence, comparing options transparently, generating an actionable plan, remembering approved preferences, and providing timely assistance when needed.

**DecisionOS is not just a tool that tells users what they could do. It helps them understand what makes sense, decide what to do next, and follow through on their decisions.**
