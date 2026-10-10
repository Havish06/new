"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, fmtTime, fmtWhen, Memory, Task, TYPE_LABEL } from "@/lib/api";
import AskBar from "@/components/AskBar";
import { Empty, ErrorNote, Pill, Section, Spinner } from "@/components/ui";

type Dash = {
  greeting: string; now: string; mode: string;
  today: { tasks_remaining: number; deadlines_approaching: number; events: number };
  up_next: { time: string; title: string; kind: string; id: string }[];
  decisions_in_progress: { id: string; query: string; decision_type: string; status: string; headline?: string; options?: number }[];
  forgotten: Task[]; proposed_memories: Memory[]; metrics: Record<string, any>;
  activity: { enabled: boolean; agent_online: boolean; app?: string; project?: string; idle_min?: number; active_streak_min?: number };
  health: { llm: boolean; llm_error?: string | null; live_search: boolean; demo_mode: boolean };
};

export default function Dashboard() {
  const [d, setD] = useState<Dash | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [searchesLeft, setSearchesLeft] = useState<number | null>(null);
  const load = useCallback(() => api<Dash>("/api/dashboard").then(setD).catch((e) => setError(e.message)), []);
  useEffect(() => { api<any>("/api/serpapi/account").then((r) => setSearchesLeft(r.account?.total_searches_left ?? null)).catch(() => {}); }, []);
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  if (error && !d) return <ErrorNote error={`Can't reach the DecisionOS backend (${error}). Is it running on port 8000?`} />;
  if (!d) return <Spinner />;

  const m = d.metrics;
  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="label">{new Date(d.now).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })}</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">{d.greeting}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Pill tone={d.mode === "focus" || d.mode === "sleep" ? "warn" : "muted"}>{d.mode} mode</Pill>
          {!d.health.llm && (
            <span title={d.health.llm_error || undefined}>
              <Pill tone="warn">{d.health.llm_error?.includes("not set") ? "Claude API not configured" : "Claude API failing — basic mode"}</Pill>
            </span>
          )}
          {d.health.demo_mode && <Pill tone="accent">Demo data (no SerpApi key)</Pill>}
          {searchesLeft != null && searchesLeft < 40 && <Pill tone="warn">{searchesLeft} SerpApi searches left</Pill>}
        </div>
      </header>

      <section className="card grid grid-cols-3 divide-x divide-line">
        {[
          ["Tasks remaining today", d.today.tasks_remaining],
          ["Deadlines in 24 h", d.today.deadlines_approaching],
          ["Events today", d.today.events],
        ].map(([label, n]) => (
          <div key={label as string} className="px-5 py-4">
            <p className="font-mono text-3xl">{n}</p>
            <p className="mt-1 text-xs text-muted">{label}</p>
          </div>
        ))}
      </section>

      <div>
        <p className="label mb-2">Quick decision</p>
        <AskBar showExamples onReply={load} />
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Up next" action={<Link href="/tasks" className="text-xs text-muted hover:text-ink">All tasks →</Link>}>
          {d.up_next.length === 0 ? <Empty>Nothing scheduled. Make a decision and turn it into a plan.</Empty> : (
            <ul className="divide-y divide-line">
              {d.up_next.map((u) => (
                <li key={u.kind + u.id} className="flex items-baseline gap-4 py-2">
                  <span className="w-16 shrink-0 font-mono text-sm text-muted">{fmtTime(u.time)}</span>
                  <span className="text-sm">{u.title}</span>
                  {u.kind === "event" && <Pill>event</Pill>}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Decisions in progress" action={<Link href="/decisions" className="text-xs text-muted hover:text-ink">History →</Link>}>
          {d.decisions_in_progress.length === 0 ? <Empty>No open decisions.</Empty> : (
            <ul className="space-y-2">
              {d.decisions_in_progress.map((x) => (
                <li key={x.id}>
                  <Link href={`/decisions/${x.id}`} className="block rounded-lg border border-line px-3 py-2 hover:border-accent">
                    <p className="truncate text-sm font-medium">{x.query}</p>
                    <p className="mt-0.5 text-xs text-muted">
                      {TYPE_LABEL[x.decision_type] || "Decision"} · {x.status === "researching" ? "researching…" : x.headline || x.status}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="You may have forgotten">
          {d.forgotten.length === 0 ? <Empty>All caught up.</Empty> : (
            <ul className="space-y-2">
              {d.forgotten.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm">{t.title}</p>
                    <p className="text-xs text-bad">{t.deadline ? `Due ${fmtWhen(t.deadline)}` : `Planned ${fmtWhen(t.scheduled_start)}`}</p>
                  </div>
                  <button className="btn-ghost !py-1 !text-xs"
                    onClick={() => api(`/api/tasks/${t.id}/complete`, { method: "POST" }).then(load)}>Done</button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Workspace">
          {!d.activity.enabled ? (
            <p className="text-sm text-muted">Workspace awareness is off. <Link className="underline" href="/settings">Enable it</Link> to get idle-time suggestions.</p>
          ) : (
            <div className="space-y-1 text-sm">
              <p><Pill tone={d.activity.agent_online ? "good" : "warn"}>{d.activity.agent_online ? "agent online" : "agent offline"}</Pill></p>
              {d.activity.project && <p>Working on <b>{d.activity.project}</b> in {d.activity.app}</p>}
              {d.activity.idle_min != null && <p className="text-muted">Idle {d.activity.idle_min} min · active streak {d.activity.active_streak_min} min</p>}
            </div>
          )}
          <button className="btn-ghost mt-3 !py-1 !text-xs" title="Pretend you've been idle for 20 minutes to see an idle-time suggestion"
            onClick={() => api("/api/demo/simulate-idle?minutes=20", { method: "POST" })}>
            Simulate 20 min idle (demo)
          </button>
        </Section>
      </div>

      {d.proposed_memories.length > 0 && (
        <Section title="Should I remember this?">
          {d.proposed_memories.map((mm) => (
            <div key={mm.id} className="flex items-center justify-between gap-3 py-1">
              <p className="text-sm">{mm.content}</p>
              <div className="flex gap-2">
                <button className="btn-accent !py-1 !text-xs" onClick={() => api(`/api/memories/${mm.id}`, { method: "PATCH", json: { status: "active" } }).then(load)}>Yes</button>
                <button className="btn-ghost !py-1 !text-xs" onClick={() => api(`/api/memories/${mm.id}`, { method: "PATCH", json: { status: "rejected" } }).then(load)}>No</button>
              </div>
            </div>
          ))}
        </Section>
      )}

      <Section title="Impact">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[
            ["Steps removed (est.)", m.steps_removed_estimate],
            ["Recommendations accepted", m.decision_acceptance_pct != null ? `${m.decision_acceptance_pct}%` : "—"],
            ["Plan tasks completed", m.plan_completion_pct != null ? `${m.plan_completion_pct}%` : "—"],
            ["Searches / decision", m.avg_searches_per_decision ?? "—"],
            ["Reminders acted on", m.reminder_usefulness_pct != null ? `${m.reminder_usefulness_pct}%` : "—"],
            ["Nudges delivered", m.interventions_delivered],
            ["Nudges held back", m.interventions_suppressed],
            ["Nudge engagement", m.intervention_engagement_pct != null ? `${m.intervention_engagement_pct}%` : "—"],
          ].map(([k, v]) => (
            <div key={k as string}>
              <p className="font-mono text-xl">{v as any}</p>
              <p className="text-xs text-muted">{k}</p>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
