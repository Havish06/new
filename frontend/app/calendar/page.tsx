"use client";
import { useCallback, useEffect, useState } from "react";
import { API, api, fmtTime } from "@/lib/api";
import { Empty, Pill, Section, Spinner } from "@/components/ui";

type Ev = { id: string; title: string; start: string; end: string; location?: string; description?: string; provider: string; task_id?: string };

export default function CalendarPage() {
  const [events, setEvents] = useState<Ev[] | null>(null);
  const [health, setHealth] = useState<any>(null);
  const [form, setForm] = useState({ title: "", start: "", minutes: 60, location: "" });
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(() => {
    const from = new Date(); from.setHours(0, 0, 0, 0); from.setDate(from.getDate() - 1);
    api<Ev[]>(`/api/calendar/events?start=${encodeURIComponent(from.toISOString())}`).then(setEvents);
    api("/api/health").then(setHealth);
  }, []);
  useEffect(() => {
    load();
    if (typeof window !== "undefined" && window.location.search.includes("connected=google")) setFlash("Google Calendar connected. New events will sync.");
  }, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title || !form.start) return;
    const s = new Date(form.start);
    await api("/api/calendar/events", { method: "POST", json: {
      title: form.title, start: s.toISOString(), end: new Date(s.getTime() + form.minutes * 60000).toISOString(), location: form.location || null } });
    setForm({ title: "", start: "", minutes: 60, location: "" });
    load();
  }

  if (!events) return <Spinner />;
  const byDay = new Map<string, Ev[]>();
  events.forEach((e) => {
    const k = new Date(e.start).toDateString();
    byDay.set(k, [...(byDay.get(k) || []), e]);
  });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">Calendar</h1>
        <div className="flex flex-wrap gap-2">
          <a className="btn-ghost" href={`${API}/api/calendar/feed.ics`}>Download .ics</a>
          {health?.google_calendar_connected ? (
            <button className="btn-ghost" onClick={() => api("/api/calendar/google/disconnect", { method: "POST" }).then(load)}>Disconnect Google</button>
          ) : (
            <a className={`btn-primary ${health?.google_calendar_configured ? "" : "pointer-events-none opacity-50"}`}
              href={`${API}/api/calendar/google/connect`}
              title={health?.google_calendar_configured ? "" : "Set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET in backend/.env"}>
              Connect Google Calendar
            </a>
          )}
        </div>
      </header>
      {flash && <p className="rounded-lg bg-good/10 px-3 py-2 text-sm text-good">{flash}</p>}
      {!health?.google_calendar_connected && (
        <p className="text-sm text-muted">Events are stored in DecisionOS. Import the .ics into Google/Outlook/Apple Calendar,
          or connect Google Calendar to sync automatically (you choose; nothing is connected by default).</p>
      )}

      <Section title="Add event">
        <form onSubmit={add} className="flex flex-wrap gap-2">
          <input className="input min-w-[180px] flex-1" placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <input className="input w-auto" type="datetime-local" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
          <select className="input w-auto" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: +e.target.value })}>
            {[15, 30, 45, 60, 90, 120, 180].map((m) => <option key={m} value={m}>{m} min</option>)}
          </select>
          <input className="input w-auto" placeholder="Location" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
          <button className="btn-primary">Add</button>
        </form>
      </Section>

      {byDay.size === 0 ? <Empty>No upcoming events.</Empty> : Array.from(byDay.entries()).map(([day, evs]) => (
        <Section key={day} title={new Date(day).toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" })}>
          <ul className="divide-y divide-line">
            {evs.map((e) => (
              <li key={e.id} className="flex items-start gap-4 py-2">
                <span className="w-28 shrink-0 font-mono text-sm text-muted">{fmtTime(e.start)}–{fmtTime(e.end)}</span>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{e.title}</p>
                  {(e.location || e.description) && <p className="truncate text-xs text-muted">{[e.location, e.description].filter(Boolean).join(" · ")}</p>}
                </div>
                {e.provider === "google" && <Pill tone="good">synced</Pill>}
                <button className="text-xs text-muted hover:text-bad" onClick={() => api(`/api/calendar/events/${e.id}`, { method: "DELETE" }).then(load)}>Delete</button>
              </li>
            ))}
          </ul>
        </Section>
      ))}
    </div>
  );
}
