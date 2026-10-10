"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Decision, fmtWhen, PlanStep } from "@/lib/api";
import { Pill, Spinner } from "../ui";

export default function PlanPanel({ d, reload }: { d: Decision; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [calendar, setCalendar] = useState(true);
  const [done, setDone] = useState<{ tasks: any[]; events: any[] } | null>(null);
  const plan = d.plan;

  useEffect(() => { if (plan) setSelected(new Set(plan.steps.map((_, i) => i))); }, [plan]);

  async function generate() {
    setBusy(true); setErr(null);
    try { await api(`/api/decisions/${d.id}/plan`, { method: "POST" }); reload(); }
    catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function commit() {
    setBusy(true); setErr(null);
    try {
      const out = await api<any>(`/api/decisions/${d.id}/plan/commit`, {
        method: "POST", json: { steps: Array.from(selected).sort((a, b) => a - b), add_to_calendar: calendar },
      });
      setDone(out);
      reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  if (!plan) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Turn this decision into concrete steps with times, reminders and calendar blocks.</p>
        <button className="btn-accent" onClick={generate} disabled={busy}>{busy ? <Spinner /> : "Create plan"}</button>
        {err && <p className="w-full text-sm text-bad">{err}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm">{plan.summary}</p>
        <button className="text-xs text-muted hover:text-ink" onClick={generate} disabled={busy}>Regenerate</button>
      </div>
      <ul className="divide-y divide-line rounded-lg border border-line">
        {plan.steps.map((s: PlanStep, i: number) => (
          <li key={i} className="flex items-start gap-3 px-3 py-2.5">
            <input type="checkbox" className="mt-1 accent-[rgb(var(--accent))]" checked={selected.has(i)}
              onChange={(e) => { const n = new Set(selected); e.target.checked ? n.add(i) : n.delete(i); setSelected(n); }} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{s.title}</span>
                <Pill tone={s.priority === "high" || s.priority === "critical" ? "accent" : "muted"}>{s.kind}</Pill>
              </div>
              <p className="text-xs text-muted">{s.start ? fmtWhen(s.start) : "Unscheduled"} · {s.duration_min} min{s.notes ? ` · ${s.notes}` : ""}</p>
            </div>
          </li>
        ))}
      </ul>
      {d.status === "planned" && !done ? (
        <p className="text-sm text-good">✓ Plan added. See <Link className="underline" href="/tasks">Tasks</Link> and <Link className="underline" href="/calendar">Calendar</Link>.</p>
      ) : done ? (
        <p className="text-sm text-good">✓ Created {done.tasks.length} task(s) and {done.events.length} calendar event(s), with reminders.
          {" "}<Link className="underline" href="/calendar">Open calendar</Link></p>
      ) : (
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={calendar} onChange={(e) => setCalendar(e.target.checked)} /> Add to calendar</label>
          <button className="btn-accent" onClick={commit} disabled={busy || selected.size === 0}>{busy ? <Spinner /> : "Add plan"}</button>
          <span className="text-xs text-muted">Nothing is purchased or sent automatically — these are steps for you.</span>
        </div>
      )}
      {err && <p className="text-sm text-bad">{err}</p>}
    </div>
  );
}
