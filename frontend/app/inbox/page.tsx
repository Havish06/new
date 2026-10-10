"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ago, api, Intervention } from "@/lib/api";
import { runAction } from "@/lib/actions";
import { Empty, Pill, Spinner } from "@/components/ui";

export default function Inbox() {
  const router = useRouter();
  const [rows, setRows] = useState<Intervention[] | null>(null);
  const [filter, setFilter] = useState<"all" | "delivered" | "suppressed">("all");
  const load = useCallback(() => {
    api<Intervention[]>(`/api/interventions?limit=100${filter !== "all" ? `&status=${filter}` : ""}`).then(setRows);
  }, [filter]);
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, [load]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Inbox</h1>
          <p className="mt-1 text-sm text-muted">Every nudge DecisionOS considered — including the ones it held back, and why.</p>
        </div>
        <div className="flex gap-1">
          {(["all", "delivered", "suppressed"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`rounded-lg px-3 py-1.5 text-sm ${filter === f ? "bg-card ring-1 ring-line" : "text-muted"}`}>{f}</button>
          ))}
          <button className="btn-ghost !py-1.5" onClick={() => api("/api/proactive/tick", { method: "POST" }).then(load)}>Check now</button>
        </div>
      </header>
      {!rows ? <Spinner /> : rows.length === 0 ? <Empty>Nothing yet. Reminders, deadlines and idle-time suggestions will appear here.</Empty> : (
        <ul className="space-y-3">
          {rows.map((iv) => (
            <li key={iv.id} className={`card p-4 ${iv.status === "suppressed" ? "opacity-70" : ""}`}>
              <div className="flex flex-wrap items-center gap-2">
                <p className="font-medium">{iv.title}</p>
                <Pill tone={iv.status === "delivered" ? "good" : "muted"}>{iv.status}</Pill>
                {iv.response && <Pill>{iv.response}</Pill>}
                <span className="ml-auto text-xs text-muted">{iv.event_type.replace(/_/g, " ").toLowerCase()} · {ago(iv.created_at)}</span>
              </div>
              <p className="mt-1 text-sm">{iv.message}</p>
              <p className="mt-2 font-mono text-[11px] text-muted">
                score {iv.score?.toFixed(2)} = urgency {iv.components.urgency} + relevance {iv.components.relevance} + confidence {iv.components.confidence}
                {" "}− annoyance {iv.components.annoyance} − quiet {iv.components.quiet_penalty} · {iv.reason}
              </p>
              {iv.status === "delivered" && !iv.response && iv.actions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {iv.actions.map((a, i) => (
                    <button key={i} className={i === 0 && a.type !== "dismiss" ? "btn-accent !py-1 !text-xs" : "btn-ghost !py-1 !text-xs"}
                      onClick={() => runAction(iv, a, router).then(load)}>{a.label}</button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
