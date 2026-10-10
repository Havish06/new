"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, fmtWhen, Task } from "@/lib/api";
import AskBar from "@/components/AskBar";
import { Empty, Pill, Section, Spinner } from "@/components/ui";

const PRIO_TONE: Record<string, "muted" | "accent" | "bad" | "warn"> = { low: "muted", medium: "muted", high: "accent", critical: "bad" };

function toLocalInput(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 16);
}

export default function Tasks() {
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [reminders, setReminders] = useState<any[]>([]);
  const [title, setTitle] = useState("");
  const [deadline, setDeadline] = useState("");
  const [priority, setPriority] = useState("medium");
  const [showDone, setShowDone] = useState(false);

  const load = useCallback(() => {
    api<Task[]>("/api/tasks").then(setTasks);
    api<any[]>("/api/reminders").then(setReminders);
  }, []);
  useEffect(() => { load(); }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    const dl = deadline ? new Date(deadline).toISOString() : null;
    const rem = deadline ? new Date(new Date(deadline).getTime() - 30 * 60000).toISOString() : null;
    await api("/api/tasks", { method: "POST", json: { title, deadline: dl, priority, reminder_at: rem && new Date(rem) > new Date() ? rem : null } });
    setTitle(""); setDeadline(""); load();
  }

  if (!tasks) return <Spinner />;
  const open = tasks.filter((t) => t.status !== "done" && t.status !== "cancelled");
  const done = tasks.filter((t) => t.status === "done");

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-semibold tracking-tight">Tasks</h1>
      <AskBar placeholder="e.g. Remind me to submit the assignment tomorrow at 6 PM" onReply={load} />

      <Section title={`Open (${open.length})`}>
        <form onSubmit={add} className="mb-4 flex flex-wrap gap-2">
          <input className="input min-w-[200px] flex-1" placeholder="Add a task…" value={title} onChange={(e) => setTitle(e.target.value)} />
          <input className="input w-auto" type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          <select className="input w-auto" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {["low", "medium", "high", "critical"].map((p) => <option key={p}>{p}</option>)}
          </select>
          <button className="btn-primary">Add</button>
        </form>
        {open.length === 0 ? <Empty>No open tasks.</Empty> : (
          <ul className="divide-y divide-line">
            {open.map((t) => {
              const overdue = t.deadline && new Date(t.deadline) < new Date();
              return (
                <li key={t.id} className="flex items-start gap-3 py-3">
                  <button aria-label="complete" onClick={() => api(`/api/tasks/${t.id}/complete`, { method: "POST" }).then(load)}
                    className="mt-0.5 h-5 w-5 shrink-0 rounded-md border border-line hover:border-good hover:bg-good/10" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{t.title}</span>
                      <Pill tone={PRIO_TONE[t.priority]}>{t.priority}</Pill>
                      {t.status === "in_progress" && <Pill tone="warn">in progress</Pill>}
                      {t.project && <Pill>{t.project}</Pill>}
                    </div>
                    <p className={`text-xs ${overdue ? "text-bad" : "text-muted"}`}>
                      {t.scheduled_start && <>Planned {fmtWhen(t.scheduled_start)} · </>}
                      {t.deadline ? <>Due {fmtWhen(t.deadline)}</> : "No deadline"}
                      {t.meta?.place?.name && <> · {t.meta.place.name}</>}
                      {t.source_decision && <> · <Link className="underline" href={`/decisions/${t.source_decision}`}>from decision</Link></>}
                    </p>
                    {t.notes && <p className="mt-0.5 truncate text-xs text-muted">{t.notes}</p>}
                  </div>
                  <input type="datetime-local" title="Change deadline" className="hidden w-44 rounded-md border border-line bg-transparent px-2 py-1 text-xs md:block"
                    defaultValue={toLocalInput(t.deadline)}
                    onBlur={(e) => e.target.value && api(`/api/tasks/${t.id}`, { method: "PATCH", json: { deadline: new Date(e.target.value).toISOString() } }).then(load)} />
                  <button className="text-xs text-muted hover:text-bad" onClick={() => api(`/api/tasks/${t.id}`, { method: "DELETE" }).then(load)}>Delete</button>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title={`Upcoming reminders (${reminders.length})`}>
        {reminders.length === 0 ? <Empty>No pending reminders.</Empty> : (
          <ul className="space-y-1 text-sm">
            {reminders.map((r) => <li key={r.id}><span className="font-mono text-muted">{fmtWhen(r.remind_at)}</span> — {r.task_title || r.message}</li>)}
          </ul>
        )}
      </Section>

      <Section title={`Completed (${done.length})`} action={<button className="text-xs text-muted" onClick={() => setShowDone(!showDone)}>{showDone ? "Hide" : "Show"}</button>}>
        {showDone && (
          <ul className="space-y-1 text-sm text-muted">
            {done.map((t) => (
              <li key={t.id} className="flex justify-between gap-2"><span className="line-through">{t.title}</span>
                <button className="text-xs hover:text-ink" onClick={() => api(`/api/tasks/${t.id}`, { method: "PATCH", json: { status: "pending" } }).then(load)}>Undo</button></li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
