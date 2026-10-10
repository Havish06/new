# DecisionOS
## Agentic Decision, Planning & Personal Execution System

**Project Type:** AI Agent / Personal Productivity / Decision Intelligence  
**Primary Hackathon Track:** AI Agents  
**Secondary Tracks:** Commerce & Market Intelligence, Knowledge & Public Interest, Wildcard  
**Core Technology:** SerpApi + Agentic Search + Personal Memory + Task/Calendar Automation

---

# 1. Product Vision

DecisionOS is an AI-powered personal decision and execution system that helps users answer:

> **"What should I do, and what should happen next?"**

Instead of simply returning search results or conversational answers, DecisionOS:

1. Understands the user's goal.
2. Extracts constraints and preferences.
3. Searches the live web for current information.
4. Compares available options.
5. Makes a reasoned recommendation.
6. Converts the decision into an actionable plan.
7. Remembers relevant decisions, preferences, and unfinished tasks.
8. Schedules actions when appropriate.
9. Reminds the user at the right time.
10. Optionally observes workspace activity to detect prolonged idle periods.
11. Uses context and past behavior to suggest useful next actions.

The fundamental philosophy is:

> **Information → Decision → Plan → Action → Memory → Future Assistance**

---

# 2. Problem

Modern users have access to enormous amounts of information but still spend significant time deciding what to do.

A typical task may require:

- Google Search
- Google Maps
- Shopping websites
- Reviews
- Reddit
- Price comparison
- Calendar
- Notes
- Reminders
- Route planning
- Personal memory

The user becomes the integration layer between all these services.

DecisionOS attempts to remove that burden.

---

# 3. Core Example

User:

> "I have an interview tomorrow at 10 AM. I need formal shoes, I need to print my resume, and I need to reach the office by 9:30. I have ₹3,000."

DecisionOS decomposes this into:

```text
INTERVIEW TOMORROW
        │
        ├── Find formal shoes
        ├── Find printing service
        ├── Determine travel route
        ├── Calculate required departure time
        ├── Check current traffic/travel information
        ├── Check store availability/timings
        └── Stay within ₹3,000
```

It searches current information and produces:

```text
YOUR PLAN

07:00
Wake up

07:30
Leave hostel

07:50
Buy formal shoes
₹1,799

08:20
Print resume
₹40

08:40
Travel to interview location

09:20
Arrive

09:30
Interview preparation

10:00
Interview
```

DecisionOS can then:

- add the interview to the calendar
- create reminders
- remember that the user has an interview
- remind the user about the shoes
- remind the user to carry their resume
- optionally notice that the user is idle later and suggest interview preparation

---

# 4. Product Principles

## 4.1 Don't just answer

Bad:

> "Here are five laptop recommendations."

Good:

> "Given your ₹70,000 budget, programming workload and preference for battery life, option #2 is the best fit."

---

## 4.2 Every recommendation should have reasoning

The system should explain:

- What it considered
- What constraints mattered
- What it rejected
- Why the final option won

---

## 4.3 Current information must be searched

For information that can change:

- prices
- availability
- opening hours
- travel time
- events
- flights
- products
- local businesses
- news

DecisionOS should search live sources rather than relying exclusively on model knowledge.

---

## 4.4 User remains in control

The system should NEVER silently:

- purchase something
- send an important message
- delete data
- modify important calendar events
- make financial commitments

Actions should require confirmation when appropriate.

---

# 5. Core Features

## Feature 1 — Decision Engine

The primary feature.

User enters a natural-language goal.

Examples:

> "Which laptop should I buy?"

> "Where should I repair my laptop?"

> "What's the cheapest way to get to Bangalore?"

> "Should I buy this online or locally?"

> "I need to prepare for my interview tomorrow."

DecisionOS extracts:

```text
Goal
Constraints
Budget
Deadline
Location
Preferences
Priorities
Required information
```

---

# 6. Constraint Extraction

Example:

> "I need a laptop for coding under ₹70,000, preferably lightweight, and I need it this week."

Structured representation:

```json
{
  "goal": "buy laptop",
  "budget": {
    "max": 70000,
    "currency": "INR"
  },
  "priority": [
    "coding performance",
    "portability"
  ],
  "deadline": "this week",
  "location": "user location"
}
```

The system should distinguish:

### Hard constraints

Must be satisfied.

```text
Budget <= ₹70,000
Delivery <= 7 days
```

### Soft constraints

Preferences.

```text
Lightweight
Good battery
Preferred brand
```

---

# 7. Search Planning Agent

The system determines what information it needs.

Example:

```text
User goal
    ↓
"What laptop should I buy?"
    ↓
Need:
    ├── Current prices
    ├── Specifications
    ├── Availability
    ├── Reviews
    ├── Alternatives
    └── User preference matching
```

The Search Planning Agent creates searches dynamically.

---

# 8. SerpApi Integration

SerpApi becomes the primary live information layer.

Potential sources:

### Google Search

General information, reviews, specifications and current information.

### Google Shopping

Product:

- prices
- merchants
- availability
- alternatives

### Google Maps

Local:

- businesses
- services
- locations
- ratings
- opening information

### Google News

Current events and changing information.

### Google Flights

Travel decisions.

Other SerpApi engines can be integrated when relevant.

The agent should choose the appropriate search engine based on the user's goal.

---

# 9. Multi-Agent Architecture

DecisionOS can use specialized agents.

```text
                    USER
                      │
                      ▼
             ┌─────────────────┐
             │ Intent Agent    │
             └────────┬────────┘
                      │
                      ▼
             ┌─────────────────┐
             │ Decision Agent  │
             └────────┬────────┘
                      │
             ┌────────┴─────────┐
             ▼                  ▼
      Search Planner       Memory Agent
             │                  │
             ▼                  │
      ┌──────────────┐           │
      │ SerpApi      │           │
      └──────┬───────┘           │
             │                   │
       ┌─────┼─────┐             │
       ▼     ▼     ▼             ▼
   Search Shopping Maps      User Context
       │     │     │             │
       └─────┼─────┘             │
             ▼                   │
       Evidence Engine ◄─────────┘
             │
             ▼
       Decision Engine
             │
             ▼
       Plan Generator
             │
       ┌─────┼──────────┐
       ▼     ▼          ▼
   Calendar Tasks    Reminders
             │
             ▼
          Memory
```

---

# 10. Evidence Engine

Search results should not immediately become recommendations.

The Evidence Engine:

1. Collects results.
2. Removes duplicates.
3. Normalizes information.
4. Identifies contradictions.
5. Scores source reliability.
6. Extracts relevant facts.
7. Associates facts with sources.

Example:

```text
Product A

Price:
₹64,990

Rating:
4.5

Weight:
1.7 kg

RAM:
16 GB

Source confidence:
HIGH
```

---

# 11. Decision Engine

The Decision Engine scores candidates according to the user's priorities.

Example:

```text
Score =
    0.35 × performance
  + 0.25 × price/value
  + 0.20 × availability
  + 0.10 × battery
  + 0.10 × portability
```

Weights are generated from user priorities.

The system should not pretend these numbers are objective truth.

They represent:

> **"Best according to your stated preferences."**

---

# 12. Decision Explanation

Every recommendation should contain:

### Why this won

### What was considered

### What was rejected

### What could change the recommendation

Example:

> **ASUS XYZ wins for you.**
>
> It is ₹5,000 below your maximum budget, has sufficient performance for your workload and is currently available locally.
>
> A Lenovo alternative has better battery life, but costs ₹8,000 more.

This creates transparency.

---

# 13. Plan Generator

After reaching a decision, DecisionOS asks:

> **What needs to happen next?**

The recommendation becomes a plan.

Example:

```text
Decision:
Buy laptop X

Plan:

1. Visit store
2. Verify configuration
3. Purchase
4. Transfer files
5. Install development environment
```

Tasks receive:

```json
{
  "title": "Visit laptop store",
  "deadline": "...",
  "priority": "high",
  "status": "pending",
  "source_decision": "laptop_purchase"
}
```

---

# 14. Personal Memory

DecisionOS should maintain a structured memory layer.

Not everything should be remembered.

Store useful long-term context such as:

### Preferences

```text
Prefers local stores
Usually prioritizes value
Budget-conscious
Prefers lightweight laptops
```

### Decisions

```text
Chose laptop X
Reason: battery + price
```

### Tasks

```text
Print resume
Deadline: tomorrow
Status: pending
```

### Projects

```text
EVRoute
Ivy
DecisionOS
```

### Habits

Only when confidently observed or explicitly stated.

---

# 15. Memory Safety

The system should distinguish:

### Explicit memory

User says:

> "Remember that I prefer buying locally."

Store it.

### Inferred preference

The system notices:

> User selected local stores three times.

This should NOT immediately become permanent memory.

Instead:

> "You seem to prefer local stores. Should I remember this?"

This avoids unwanted profiling.

---

# 16. Task & Reminder System

Users can say:

> "Remind me to submit this tomorrow at 6 PM."

DecisionOS creates:

```text
Task:
Submit assignment

Due:
Tomorrow 6:00 PM

Reminder:
Tomorrow 5:00 PM
```

---

# 17. Calendar Integration

Support calendar providers through an abstraction layer.

```text
CalendarService
      │
      ├── Google Calendar
      │
      ├── Yahoo Calendar
      │
      └── Future providers
```

The application should not hard-code calendar logic into the agent.

Example:

```typescript
interface CalendarProvider {
    createEvent(event): Promise<Event>
    updateEvent(id, event): Promise<Event>
    deleteEvent(id): Promise<void>
}
```

The user should explicitly connect the calendar.

---

# 18. Notification System

DecisionOS should support:

### Browser notifications

### Desktop notifications

### Mobile notifications

### Email

Potential future integrations:

- Telegram
- WhatsApp
- Discord

Notifications should be context-aware.

Bad:

> "Reminder: Task pending."

Better:

> "You planned to print your resume before your 10 AM interview tomorrow. You haven't marked it complete yet."

---

# 19. Intelligent Reminder System

Reminders shouldn't simply be alarms.

They should understand context.

Example:

```text
Task:
Buy formal shoes

Deadline:
Tomorrow 8 AM

Current:
Today 7 PM

Store:
Open until 9 PM

DecisionOS:
"You still need formal shoes for tomorrow's interview.
The store you selected closes at 9 PM and is 15 minutes away."
```

This turns reminders into useful interventions.

---

# 20. Workspace Awareness

Optional advanced feature.

DecisionOS can connect to the user's workspace.

Examples:

- VS Code
- Desktop activity
- browser activity
- project folders
- development environment

The system should NOT capture arbitrary private content by default.

Instead, collect high-level signals such as:

```text
Active application
Active project
Activity duration
Last interaction
Task context
```

Example:

```text
VS Code
Project: EVRoute
Active: 42 minutes
Last activity: 18 minutes ago
```

---

# 21. Idle Detection

The system can detect prolonged inactivity.

Example:

```text
User activity:

10:00  VS Code
10:15  VS Code
10:30  VS Code
10:45  No interaction
11:00  No interaction
```

DecisionOS determines:

> User may be idle.

But **idle does not automatically mean interruption is appropriate.**

The system evaluates:

```text
Idle duration
+
Current time
+
Calendar
+
User preferences
+
Current project
+
Pending tasks
+
Recent activity
```

---

# 22. Intelligent Idle Suggestions

If the user is idle, DecisionOS may suggest:

### Resume something unfinished

> "You were working on EVRoute earlier. You still had the route-energy calculation task pending."

### Something they planned

> "You planned to submit the assignment today. Want me to open the relevant project?"

### Something they enjoy

If explicitly enabled:

> "You usually work on your music project around this time. Want to continue?"

### Useful break

> "You've been working for 2 hours. Want a 10-minute break?"

The system should avoid becoming annoying.

---

# 23. Idle Suggestion Priority

Use a priority hierarchy:

```text
1. Critical deadline
2. Time-sensitive task
3. Explicitly planned task
4. Unfinished current project
5. Recently abandoned task
6. User's known interests
7. Optional recommendation
```

Example:

If an assignment is due in 2 hours:

> Don't suggest gaming.

If there is nothing urgent:

> Suggest something useful or enjoyable.

---

# 24. Bedtime / Quiet Hours

The user defines:

```text
Quiet hours:
11:00 PM – 7:00 AM
```

During this period:

- No idle suggestions
- No non-critical notifications
- No background interventions

Critical notifications can optionally override this.

---

# 25. Intervention Policy

DecisionOS should use an interruption score.

Conceptually:

```text
intervention_score =
    urgency
  + relevance
  + confidence
  - annoyance
  - quiet_hours_penalty
```

Only notify when the score exceeds a threshold.

This prevents:

> "AI constantly talking to me."

The goal is:

> **Helpful when needed. Invisible when not needed.**

---

# 26. User Modes

### Focus Mode

No interruptions.

### Normal Mode

Useful suggestions allowed.

### Assistant Mode

More proactive.

### Quiet Mode

Only important reminders.

### Sleep Mode

No proactive interaction.

---

# 27. Example End-to-End Scenario

User:

> "I have a presentation tomorrow at 9 AM. I haven't prepared anything."

DecisionOS:

### Step 1 — Understand

```text
Deadline:
Tomorrow 9 AM

Task:
Prepare presentation
```

### Step 2 — Plan

```text
Tonight:
Research
Create outline
Prepare slides

Tomorrow:
Review
Practice
Travel
```

### Step 3 — Schedule

Creates calendar blocks.

### Step 4 — Search

If necessary:

- presentation resources
- relevant research
- examples
- current information

### Step 5 — Reminder

At 7 PM:

> "Your presentation preparation block starts in 30 minutes."

### Step 6 — Workspace awareness

User opens VS Code but spends 25 minutes doing unrelated activity.

DecisionOS:

> "You planned to start the presentation. Want me to open your presentation workspace?"

### Step 7 — Completion

User marks it complete.

Memory records:

```text
Presentation prepared
```

---

# 28. Dashboard

The main dashboard should NOT be a generic chatbot.

It should show:

```text
GOOD AFTERNOON, HAVISH

┌──────────────────────────────────────────┐
│ TODAY                                    │
│                                          │
│ 3 tasks remaining                        │
│ 1 deadline approaching                   │
│ 2 scheduled events                       │
└──────────────────────────────────────────┘

UP NEXT

10:30  Finish EVRoute routing
12:00  Lunch
14:00  Submit assignment

──────────────────────────────────────────

DECISION IN PROGRESS

Laptop purchase
3 options compared
Recommendation ready

──────────────────────────────────────────

YOU MAY HAVE FORGOTTEN

Resume printing
Due tomorrow

──────────────────────────────────────────

QUICK DECISION

What are you trying to figure out?
```

---

# 29. Decision View

```text
DECISION

Which laptop should I buy?

CONSTRAINTS
₹70,000 maximum
Coding
Lightweight
This week

RESEARCH
43 products
17 sellers
126 reviews

RECOMMENDATION

ASUS XYZ
₹64,990

WHY?

✓ Best performance/value
✓ Available this week
✓ 16 GB RAM
✓ Good battery

ALTERNATIVES

Cheapest
₹58,999

Best Performance
₹69,999

[See Evidence]
[Create Purchase Plan]
```

---

# 30. Memory View

Users should be able to see what the AI remembers.

```text
MEMORY

Preferences

✓ Budget-conscious
✓ Prefers local stores

Projects

✓ EVRoute
✓ Ivy

Upcoming

✓ Interview — Tomorrow
✓ Assignment — Friday

Past decisions

✓ Laptop selection
✓ Travel plan
```

Every memory should be:

- editable
- deletable
- inspectable

---

# 31. Privacy Architecture

This feature is extremely important because workspace monitoring is sensitive.

The default should be:

### Local-first activity processing

Where possible:

```text
Desktop Activity
       ↓
Local Activity Monitor
       ↓
High-level event
       ↓
DecisionOS
```

Do NOT continuously upload:

- screenshots
- keystrokes
- passwords
- private documents
- arbitrary browser contents

unless explicitly enabled.

---

# 32. Permissions

Workspace monitoring should be opt-in.

Example:

```text
WORKSPACE AWARENESS

[ ] Enable activity awareness

If enabled, DecisionOS can detect:
✓ active application
✓ project name
✓ inactivity duration

It will NOT collect:
✗ keystrokes
✗ passwords
✗ screenshots
✗ private file contents
```

The user can pause monitoring instantly.

---

# 33. Technical Architecture

```text
                    ┌──────────────┐
                    │   Web App    │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ API Gateway  │
                    └──────┬───────┘
                           │
             ┌─────────────┼──────────────┐
             ▼             ▼              ▼
       Agent Engine    Memory Engine   Task Engine
             │             │              │
             ▼             ▼              ▼
       Search Planner   Vector/DB     Scheduler
             │
             ▼
          SerpApi
             │
     ┌───────┼────────┐
     ▼       ▼        ▼
  Search  Shopping   Maps
             │
             ▼
      Evidence Engine
             │
             ▼
      Decision Engine
             │
             ▼
       Plan Generator
             │
     ┌───────┼─────────┐
     ▼       ▼         ▼
 Calendar  Reminder  Workspace
```

---

# 34. Suggested Stack

## Frontend

```text
Next.js
React
TypeScript
Tailwind CSS
```

## Backend

```text
Node.js
TypeScript
```

or Python if the agent/search layer is easier to implement there.

## Agent

```text
Python
serpapi-search-tools
```

Potentially expose the agent through an API to the frontend.

## Database

```text
PostgreSQL
```

Supabase can be used for:

- authentication
- database
- realtime
- row-level security

## Cache

```text
Redis
```

Useful for:

- search caching
- sessions
- temporary agent state
- rate limiting

## Scheduling

A backend job scheduler.

Example:

```text
BullMQ + Redis
```

---

# 35. Core Database Entities

```text
users

user_preferences

memories

projects

decisions

decision_constraints

decision_evidence

decision_options

tasks

reminders

calendar_events

activity_events

interventions

notification_preferences
```

---

# 36. Decision Data Model

Example:

```json
{
  "id": "decision_123",
  "user_id": "user_123",
  "goal": "Buy laptop for college",
  "status": "completed",
  "constraints": {
    "budget_max": 70000,
    "location": "Chennai",
    "deadline": "2026-10-14"
  },
  "priorities": [
    "performance",
    "battery",
    "value"
  ],
  "recommendation": "product_456",
  "created_at": "...",
  "updated_at": "..."
}
```

---

# 37. Task Model

```json
{
  "title": "Print resume",
  "status": "pending",
  "priority": "high",
  "deadline": "...",
  "source": "decision_123",
  "reminder_at": "...",
  "calendar_event_id": null
}
```

---

# 38. Agent Tools

The agent should have explicit tools rather than unrestricted access.

Example:

```text
search_web()
search_shopping()
search_maps()
search_news()
search_flights()

get_user_memory()
save_memory()

create_task()
update_task()
complete_task()

create_calendar_event()
update_calendar_event()

schedule_reminder()

get_current_time()
get_user_preferences()
```

Workspace:

```text
get_active_application()
get_current_project()
get_idle_duration()
```

---

# 39. Agent Loop

Conceptually:

```text
USER REQUEST
     ↓
UNDERSTAND
     ↓
DO WE NEED CURRENT INFORMATION?
     │
   YES
     ↓
PLAN SEARCHES
     ↓
SEARCH
     ↓
COLLECT EVIDENCE
     ↓
COMPARE
     ↓
DECIDE
     ↓
DOES USER NEED ACTION?
     │
   YES
     ↓
CREATE PLAN
     ↓
SCHEDULE / REMIND
     ↓
SAVE RELEVANT MEMORY
     ↓
MONITOR PLAN
     ↓
FOLLOW UP WHEN APPROPRIATE
```

---

# 40. Proactive Agent Loop

A background service periodically evaluates:

```text
Current time
Calendar
Pending tasks
Deadlines
Recent decisions
User activity
Quiet hours
User preferences
```

Then:

```text
Should I intervene?

NO → remain silent

YES → generate suggestion
```

The agent should NEVER continuously ask an LLM every few seconds.

Use event-driven triggers.

---

# 41. Event-Driven Architecture

Examples:

```text
TASK_DUE_SOON

CALENDAR_EVENT_APPROACHING

USER_IDLE

DEADLINE_CHANGED

SEARCH_RESULT_EXPIRED

TASK_OVERDUE

PROJECT_ABANDONED

USER_RETURNED

QUIET_HOURS_STARTED

QUIET_HOURS_ENDED
```

This makes the system cheaper and easier to scale.

---

# 42. MVP

For the hackathon, DO NOT build everything.

Build this first:

### Phase 1

- Natural-language goal
- Constraint extraction
- SerpApi search
- Multi-source comparison
- Decision recommendation
- Evidence
- Explanation

### Phase 2

- Plan generation
- Tasks
- Reminders
- Calendar integration

### Phase 3

- Memory
- User preferences
- Follow-up questions

### Phase 4

- Workspace activity
- Idle detection
- Proactive suggestions

---

# 43. Hackathon Demo

The demo should tell one story.

User:

> "I need to attend an interview tomorrow at 10 AM. I need formal shoes, printed resumes and a way to reach the office by 9:30. My budget is ₹2,500."

DecisionOS searches live information.

Then produces:

```text
INTERVIEW PLAN

Shoes
₹1,599
4.5★

Printing
₹60

Transport
₹120

TOTAL
₹1,779

✓ Within budget

TIMELINE

07:00 Wake up
07:30 Leave
07:50 Buy shoes
08:20 Print resume
08:35 Travel
09:20 Arrive
10:00 Interview
```

Then:

> **"Would you like me to add this plan to your calendar?"**

User clicks:

**Add Plan**

Calendar events appear.

Later:

> User becomes idle.

DecisionOS notices:

> "You haven't prepared your interview answers yet. You planned 30 minutes for this. Continue?"

That final interaction demonstrates the project's unique value.

---

# 44. What Makes DecisionOS Different

The competitive advantage should NOT be:

> "We use AI."

It should be:

### 1. Decision-oriented

Not search-oriented.

### 2. Constraint-aware

Budget, time, distance, preferences and deadlines.

### 3. Evidence-backed

Every recommendation can be traced to live information.

### 4. Actionable

A decision becomes a plan.

### 5. Persistent

The system remembers relevant context.

### 6. Proactive

It can follow up later.

### 7. Context-aware

It understands time, tasks and workspace state.

### 8. User-controlled

The user controls memory, monitoring and notifications.

---

# 45. Product Positioning

## One-line pitch

> **DecisionOS turns "What should I do?" into a researched decision, an actionable plan, and timely follow-through.**

## Short pitch

> The internet gives you information, but it doesn't make the decision for you. DecisionOS uses live web search, personal context and constraint-based reasoning to determine what makes the most sense for you, turns the decision into a plan, remembers what matters and helps you follow through.

## Tagline

> **Don't search. Decide. Act.**

Alternative:

> **From "What should I do?" to "Here's what happens next."**

---

# 46. Important Scope Boundary

The system should **not** become an unrestricted surveillance agent.

Workspace awareness is a supporting feature, not the product's foundation.

The hierarchy should be:

```text
DECISION
   ↓
PLAN
   ↓
TASK
   ↓
REMINDER
   ↓
FOLLOW-UP
   ↓
OPTIONAL WORKSPACE AWARENESS
```

This keeps the project useful even when workspace monitoring is disabled.

---

# 47. Success Metrics

The system should measure:

### Decision quality

Did the user accept the recommendation?

### Plan completion

What percentage of generated tasks are completed?

### Reminder usefulness

How often are reminders dismissed vs acted upon?

### Intervention quality

How often does the user interact with proactive suggestions?

### Search efficiency

How many searches were required to reach a recommendation?

### User effort

How many actions did DecisionOS eliminate?

The ultimate metric:

> **How many steps did DecisionOS remove between the user's intention and completion?**

---

# 48. Final Product Definition

DecisionOS is not:

> A chatbot.

It is not:

> A search engine.

It is not:

> A calendar.

It is not:

> A task manager.

It is a layer that connects all four.

```text
                USER INTENTION
                      │
                      ▼
               ┌─────────────┐
               │ UNDERSTAND  │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │   RESEARCH  │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │   DECIDE    │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │    PLAN     │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │   EXECUTE   │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │   REMEMBER  │
               └──────┬──────┘
                      ▼
               ┌─────────────┐
               │  FOLLOW UP  │
               └─────────────┘
```

### The core loop:

> **Decide → Plan → Remember → Act → Learn → Help again.**

That is the product we should build.