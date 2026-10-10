"use client";
import { useCallback, useEffect, useState } from "react";
import { api, fmtWhen, Memory, Task } from "@/lib/api";
import { Empty, Pill, Section, Spinner } from "@/components/ui";

const GROUPS: [string, string][] = [
  ["preference", "Preferences"], ["project", "Projects"], ["habit", "Habits"], ["interest", "Interests"],
  ["fact", "Facts"], ["task", "Appointments"], ["decision", "Past decisions"],
];

function Row({ m, reload }: { m: Memory; reload: () => void }) {
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(m.content);
  return (
    <li className="flex items-start gap-3 py-2">
      <span className="mt-0.5 text-good">✓</span>
      <div className="min-w-0 flex-1">
        {edit ? (
          <form onSubmit={(e) => { e.preventDefault(); api(`/api/memories/${m.id}`, { method: "PATCH", json: { content: text } }).then(() => { setEdit(false); reload(); }); }}>
            <input className="input !py-1" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          </form>
        ) : <p className="text-sm">{m.content}</p>}
        <p className="text-xs text-muted">{m.source === "explicit" ? "you told me" : m.source === "inferred" ? "confirmed by you" : "recorded automatically"} · {fmtWhen(m.updated_at)}</p>
      </div>
      <button className="text-xs text-muted hover:text-ink" onClick={() => setEdit(!edit)}>{edit ? "Cancel" : "Edit"}</button>
      <button className="text-xs text-muted hover:text-bad" onClick={() => api(`/api/memories/${m.id}`, { method: "DELETE" }).then(reload)}>Delete</button>
    </li>
  );
}

export default function MemoryPage() {
  const [mems, setMems] = useState<Memory[] | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [text, setText] = useState("");

  const load = useCallback(() => {
    api<Memory[]>("/api/memories").then(setMems);
    api<Task[]>("/api/tasks?status=open").then(setTasks);
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!mems) return <Spinner />;
  const active = mems.filter((m) => m.status === "active");
  const proposed = mems.filter((m) => m.status === "proposed");
  const upcoming = tasks.filter((t) => t.deadline).slice(0, 8);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Memory</h1>
        <p className="mt-1 text-sm text-muted">Everything DecisionOS remembers about you. Inferred patterns are only kept after you confirm them. Edit or delete anything.</p>
      </header>

      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) api("/api/memories", { method: "POST", json: { content: text } }).then(() => { setText(""); load(); }); }} className="flex gap-2">
        <input className="input" placeholder="e.g. I prefer buying from local stores" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn-primary shrink-0">Remember</button>
      </form>

      {proposed.length > 0 && (
        <Section title="Waiting for your confirmation">
          {proposed.map((m) => (
            <div key={m.id} className="flex items-center justify-between gap-3 py-1">
              <p className="text-sm">{m.content} <Pill>seen {m.meta?.count}×</Pill></p>
              <div className="flex gap-2">
                <button className="btn-accent !py-1 !text-xs" onClick={() => api(`/api/memories/${m.id}`, { method: "PATCH", json: { status: "active" } }).then(load)}>Remember</button>
                <button className="btn-ghost !py-1 !text-xs" onClick={() => api(`/api/memories/${m.id}`, { method: "PATCH", json: { status: "rejected" } }).then(load)}>Don&apos;t</button>
              </div>
            </div>
          ))}
        </Section>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        {GROUPS.map(([kind, label]) => {
          const items = active.filter((m) => m.kind === kind);
          if (!items.length && !["preference", "project"].includes(kind)) return null;
          return (
            <Section key={kind} title={label}>
              {items.length === 0 ? <Empty>Nothing yet.</Empty> : <ul className="divide-y divide-line">{items.map((m) => <Row key={m.id} m={m} reload={load} />)}</ul>}
            </Section>
          );
        })}
        <Section title="Upcoming">
          {upcoming.length === 0 ? <Empty>No deadlines.</Empty> : (
            <ul className="space-y-1 text-sm">{upcoming.map((t) => <li key={t.id}>✓ {t.title} — <span className="text-muted">{fmtWhen(t.deadline)}</span></li>)}</ul>
          )}
        </Section>
      </div>
    </div>
  );
}
