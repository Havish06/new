"use client";
import { useState } from "react";
import { api, Decision, inr, Scenario } from "@/lib/api";
import { Spinner } from "../ui";

export default function WhatIfPanel({ d, reload, busyExternal }: { d: Decision; reload: () => void; busyExternal?: boolean }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const r = d.result;
  const scenarios: Scenario[] = r.scenarios || [];
  const budget = d.spec?.hard_constraints?.budget_max;
  const byId = Object.fromEntries(d.candidates.map((c) => [c.id, c]));
  const baseName = d.decision_type === "errands"
    ? `~${inr(r.totals?.cost)}, ${r.totals?.duration_min} min`
    : byId[r.winner]?.name || "No option qualifies";

  const suggestions = d.decision_type === "errands"
    ? ["What if I only want places rated 4.5+?", "What if everything must be within 2 km?",
       budget ? `What if my budget is ${inr(budget * 0.7)}?` : "What if my budget is ₹500?"]
    : [
        budget ? `What if my budget is ${inr(budget * 1.15)}?` : "What if my budget is lower?",
        ...(d.spec?.criteria || []).slice(1, 3).map((c: any) => `What if ${c.label.toLowerCase()} is more important?`),
        d.decision_type === "commerce" ? "What if I need it today?" : null,
      ].filter(Boolean) as string[];

  async function run(q: string) {
    setBusy(true); setErr(null);
    try {
      await api(`/api/decisions/${d.id}/whatif`, { method: "POST", json: { text: q } });
      setText("");
      reload();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  async function adopt(i: number) {
    setBusy(true);
    try { await api(`/api/decisions/${d.id}/scenarios/${i}/adopt`, { method: "POST" }); reload(); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) run(text); }} className="flex gap-2">
        <input className="input" placeholder="What if… (e.g. battery life matters more than performance)" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn-primary shrink-0" disabled={busy || busyExternal}>{busy ? <Spinner /> : "Recalculate"}</button>
      </form>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s) => <button key={s} className="chip hover:border-accent hover:text-ink" onClick={() => run(s)}>{s}</button>)}
      </div>
      {err && <p className="text-sm text-bad">{err}</p>}

      <div className="space-y-2">
        <p className="label">Decision graph</p>
        <div className="flex items-center gap-3 rounded-lg border border-accent/50 bg-accent/5 px-3 py-2 text-sm">
          <span className="w-48 shrink-0 font-medium">Current</span><span className="text-muted">→</span><span className="font-medium">{baseName}</span>
        </div>
        {scenarios.map((s, i) => (
          <div key={i} className="flex flex-wrap items-center gap-3 rounded-lg border border-line px-3 py-2 text-sm">
            <span className="w-48 shrink-0">{s.label}</span>
            <span className="text-muted">→</span>
            <span className={s.changed ? "font-medium text-accent" : ""}>{s.winner_name}</span>
            {s.changed === false && <span className="text-xs text-muted">(same winner)</span>}
            {s.note && <span className="w-full text-xs text-warn">{s.note}</span>}
            <button className="btn-ghost ml-auto !py-1 !text-xs" onClick={() => adopt(i)} disabled={busy}>Adopt</button>
          </div>
        ))}
        {scenarios.length === 0 && <p className="text-sm text-muted">Ask a what-if to see how the recommendation shifts. No new searches needed — the evidence is re-scored instantly.</p>}
      </div>
    </div>
  );
}
