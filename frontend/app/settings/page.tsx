"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Pill, Section, Spinner } from "@/components/ui";

const MODES: [string, string][] = [
  ["focus", "No interruptions"], ["normal", "Useful suggestions allowed"], ["assistant", "More proactive"],
  ["quiet", "Only important reminders"], ["sleep", "No proactive interaction"],
];

type Loc = { label: string; lat: number | null; lng: number | null; address?: string };

function LocationPicker({ value, onPick }: { value: Loc; onPick: (l: Loc) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<Loc[]>([]);
  const [busy, setBusy] = useState(false);
  return (
    <div className="space-y-2">
      <p className="text-sm">{value?.lat != null ? <>{value.label || "Set"} <span className="font-mono text-xs text-muted">({value.lat.toFixed(4)}, {value.lng!.toFixed(4)})</span></> : <span className="text-muted">Not set</span>}</p>
      <div className="flex flex-wrap gap-2">
        <input className="input min-w-[200px] flex-1" placeholder="Search a place or address…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-ghost" disabled={busy || !q} onClick={async () => { setBusy(true); try { setResults(await api<Loc[]>(`/api/geocode?q=${encodeURIComponent(q)}`)); } finally { setBusy(false); } }}>Search</button>
        <button className="btn-ghost" onClick={() => navigator.geolocation?.getCurrentPosition(
          (p) => onPick({ label: value?.label || "Current location", lat: p.coords.latitude, lng: p.coords.longitude }),
          () => alert("Location permission denied"))}>Use my location</button>
      </div>
      {results.length > 0 && (
        <ul className="rounded-lg border border-line text-sm">
          {results.map((r, i) => (
            <li key={i}><button className="w-full px-3 py-1.5 text-left hover:bg-paper" onClick={() => { onPick(r); setResults([]); setQ(""); }}>
              {r.label} <span className="text-xs text-muted">{r.address}</span></button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const [s, setS] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [serp, setSerp] = useState<any>(null);
  const [saved, setSaved] = useState(false);
  const [newPlace, setNewPlace] = useState("");

  const load = useCallback(() => {
    api("/api/settings").then(setS);
    api("/api/activity/status").then(setStatus);
    api("/api/health").then(setHealth);
    api("/api/serpapi/account").then((r: any) => setSerp(r.account)).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);

  async function patch(p: any) {
    const next = await api("/api/settings", { method: "PATCH", json: p });
    setS(next);
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
  }

  if (!s) return <Spinner />;
  const ws = s.workspace;
  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        {saved && <Pill tone="good">saved</Pill>}
      </header>

      {health && (
        <Section title="System">
          <div className="flex flex-wrap gap-2 text-sm">
            <Pill tone={health.llm ? "good" : "warn"}>{health.llm ? `Claude: ${health.model}` : health.model ? "Claude API key rejected" : "Claude API key missing"}</Pill>
            <Pill tone={health.live_search ? "good" : "accent"}>{health.live_search ? "SerpApi live search" : "Demo search data"}</Pill>
            <Pill tone={health.google_calendar_connected ? "good" : "muted"}>Google Calendar {health.google_calendar_connected ? "connected" : "not connected"}</Pill>
          </div>
          {health.llm_error && <p className="mt-2 text-xs text-muted">Claude: {health.llm_error}</p>}
          {serp && (
            <p className={`mt-2 text-sm ${serp.total_searches_left < 25 ? "text-warn" : "text-muted"}`}>
              SerpApi {serp.plan_name}: <span className="font-mono">{serp.total_searches_left}</span> of {serp.searches_per_month} searches
              left this month ({serp.this_month_usage} used). A trip plan uses ~16, most other questions 2–5; repeats within 30 min are free.
            </p>
          )}
        </Section>
      )}

      <Section title="You">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm">Name
            <input className="input mt-1" defaultValue={s.name} onBlur={(e) => patch({ name: e.target.value })} />
          </label>
          <label className="block text-sm">Time zone
            <input className="input mt-1" defaultValue={s.timezone} onBlur={(e) => patch({ timezone: e.target.value })} />
          </label>
        </div>
        <div className="mt-4">
          <p className="mb-1 text-sm font-medium">Home / hostel (start point for local decisions & errands)</p>
          <LocationPicker value={s.home} onPick={(l) => patch({ home: { label: l.label, lat: l.lat, lng: l.lng } })} />
        </div>
        <div className="mt-5">
          <p className="mb-1 text-sm font-medium">Saved places <span className="font-normal text-muted">(e.g. college, office — used when you say “reach college by 4 PM”)</span></p>
          {Object.entries(s.places || {}).map(([k, v]: any) => (
            <div key={k} className="mb-3 rounded-lg border border-line p-3">
              <div className="mb-1 flex justify-between"><span className="font-medium">{k}</span>
                <button className="text-xs text-muted hover:text-bad" onClick={() => { const p = { ...s.places }; delete p[k]; api("/api/settings", { method: "PATCH", json: { places: null } }).then(() => patch({ places: p })); }}>Remove</button></div>
              <LocationPicker value={v} onPick={(l) => patch({ places: { [k]: { label: l.label, lat: l.lat, lng: l.lng, address: l.address } } })} />
            </div>
          ))}
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (newPlace.trim()) { patch({ places: { [newPlace.trim().toLowerCase()]: { label: newPlace.trim(), lat: null, lng: null } } }); setNewPlace(""); } }}>
            <input className="input" placeholder="Add a place name, e.g. college" value={newPlace} onChange={(e) => setNewPlace(e.target.value)} />
            <button className="btn-ghost shrink-0">Add</button>
          </form>
        </div>
      </Section>

      <Section title="Mode">
        <div className="grid gap-2 md:grid-cols-5">
          {MODES.map(([m, d]) => (
            <button key={m} onClick={() => patch({ mode: m })}
              className={`rounded-lg border p-3 text-left ${s.mode === m ? "border-accent bg-accent/5" : "border-line hover:border-muted"}`}>
              <p className="font-medium capitalize">{m}</p><p className="text-xs text-muted">{d}</p>
            </button>
          ))}
        </div>
      </Section>

      <Section title="Quiet hours">
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.quiet_hours.enabled} onChange={(e) => patch({ quiet_hours: { enabled: e.target.checked } })} /> Enabled</label>
          <label className="flex items-center gap-2">From <input type="time" className="input !w-auto !py-1" value={s.quiet_hours.start} onChange={(e) => patch({ quiet_hours: { start: e.target.value } })} /></label>
          <label className="flex items-center gap-2">to <input type="time" className="input !w-auto !py-1" value={s.quiet_hours.end} onChange={(e) => patch({ quiet_hours: { end: e.target.value } })} /></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={s.quiet_hours.allow_critical} onChange={(e) => patch({ quiet_hours: { allow_critical: e.target.checked } })} /> Let critical deadlines through</label>
        </div>
      </Section>

      <Section title="Workspace awareness" action={status && ws.enabled && <Pill tone={status.agent_online ? "good" : "warn"}>{status.agent_online ? "agent online" : "agent offline"}</Pill>}>
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-3 text-sm">
            <label className="flex items-center gap-2 font-medium"><input type="checkbox" checked={ws.enabled} onChange={(e) => patch({ workspace: { enabled: e.target.checked } })} /> Enable activity awareness</label>
            {ws.enabled && (
              <>
                <button className="btn-ghost !py-1 !text-xs" onClick={() => patch({ workspace: { paused: !ws.paused } })}>{ws.paused ? "Resume monitoring" : "Pause monitoring"}</button>
                <label className="flex items-center gap-2">Idle after <input type="number" min={5} className="input !w-20 !py-1" value={ws.idle_threshold_min} onChange={(e) => patch({ workspace: { idle_threshold_min: +e.target.value } })} /> min</label>
                <label className="flex items-center gap-2">Suggest a break after <input type="number" min={30} className="input !w-20 !py-1" value={ws.break_after_min} onChange={(e) => patch({ workspace: { break_after_min: +e.target.value } })} /> min</label>
                <label className="flex items-center gap-2"><input type="checkbox" checked={ws.suggest_interests} onChange={(e) => patch({ workspace: { suggest_interests: e.target.checked } })} /> Suggest things I enjoy when nothing is urgent</label>
                <button className="text-xs text-muted underline" onClick={() => api("/api/activity", { method: "DELETE" }).then(load)}>Delete all activity history</button>
              </>
            )}
            <p className="text-xs text-muted">Run the agent on your laptop: <code className="font-mono">python workspace_agent/agent.py</code></p>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><p className="mb-1 font-medium">Can detect</p><ul className="space-y-0.5 text-good"><li>✓ active application</li><li>✓ project name</li><li>✓ inactivity duration</li></ul></div>
            <div><p className="mb-1 font-medium">Never collects</p><ul className="space-y-0.5 text-bad"><li>✗ keystrokes</li><li>✗ passwords</li><li>✗ screenshots</li><li>✗ private file contents</li></ul></div>
          </div>
        </div>
      </Section>

      <Section title="Notifications & reminders">
        <div className="flex flex-wrap gap-4 text-sm">
          {(["browser", "desktop", "email", "telegram"] as const).map((k) => (
            <label key={k} className="flex items-center gap-2 capitalize"><input type="checkbox" checked={s.notifications[k]} onChange={(e) => patch({ notifications: { [k]: e.target.checked } })} /> {k}</label>
          ))}
          <label className="flex items-center gap-2">Remind me <input type="number" min={0} className="input !w-20 !py-1" value={s.reminder_lead_min} onChange={(e) => patch({ reminder_lead_min: +e.target.value })} /> min before</label>
        </div>
        <p className="mt-2 text-xs text-muted">Email and Telegram need SMTP / bot settings in backend/.env and only carry important nudges.</p>
      </Section>

      <Section title="Getting around (errand planning)">
        <div className="flex flex-wrap gap-4 text-sm">
          {[["walk_max_km", "Walk up to (km)"], ["walk_kmh", "Walking speed (km/h)"], ["ride_kmh", "Auto/cab speed (km/h)"], ["ride_cost_per_km", "Auto/cab ₹ per km"]].map(([k, label]) => (
            <label key={k} className="flex items-center gap-2">{label}
              <input type="number" step="0.5" className="input !w-20 !py-1" value={s.transport[k]} onChange={(e) => patch({ transport: { [k]: +e.target.value } })} /></label>
          ))}
        </div>
      </Section>
    </div>
  );
}
