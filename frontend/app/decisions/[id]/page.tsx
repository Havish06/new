"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, Decision, fmtWhen, inr, TYPE_LABEL } from "@/lib/api";
import AskBar from "@/components/AskBar";
import { ErrorNote, Pill, Spinner } from "@/components/ui";
import Recommendation from "@/components/decision/Recommendation";
import WhyPanel from "@/components/decision/WhyPanel";
import EvidencePanel from "@/components/decision/EvidencePanel";
import WhatIfPanel from "@/components/decision/WhatIfPanel";
import PlanPanel from "@/components/decision/PlanPanel";
import ErrandsView from "@/components/decision/ErrandsView";
import { Landscape, LearningPath, ResearchProgress } from "@/components/decision/Extras";
import { ResearchView, TaskPlan, TripView } from "@/components/decision/ResearchViews";

type Tab = "plan" | "why" | "whatif" | "evidence";

export default function DecisionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [d, setD] = useState<Decision | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("plan");

  const load = useCallback(() => api<Decision>(`/api/decisions/${id}`).then(setD).catch((e) => setErr(e.message)), [id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (d?.status !== "researching") return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [d?.status, load]);

  if (err) return <ErrorNote error={err} />;
  if (!d) return <Spinner />;

  const spec = d.spec || {};
  const hc = spec.hard_constraints || {};
  const ready = ["ready", "accepted", "planned"].includes(d.status);
  const isErrands = d.decision_type === "errands";
  const isResearch = d.decision_type === "general" || d.decision_type === "trip";

  async function choose(cid: string) {
    await api(`/api/decisions/${d!.id}/choose`, { method: "POST", json: { candidate_id: cid } });
    load();
  }
  async function whatIfPatch(patch: any, label: string) {
    await api(`/api/decisions/${d!.id}/whatif`, { method: "POST", json: { patch: { ...patch, label } } });
    setTab("whatif");
    load();
  }

  const TABS: [Tab, string][] = [["plan", "Plan"], ["why", "Why?"], ["whatif", "What if?"], ["evidence", "Evidence"]];

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="label">{TYPE_LABEL[d.decision_type || ""] || "Decision"}</span>
          {d.result?.demo && <Pill tone="accent">demo data</Pill>}
          {d.status === "accepted" && <Pill tone="good">accepted</Pill>}
          {d.status === "planned" && <Pill tone="good">planned</Pill>}
        </div>
        <h1 className="text-2xl font-semibold leading-snug tracking-tight md:text-3xl">{d.query}</h1>
        {spec.decision_type && (
          <div className="flex flex-wrap gap-2">
            {hc.budget_max && <span className="chip">≤ {inr(hc.budget_max)}</span>}
            {hc.deadline && <span className="chip">by {fmtWhen(hc.deadline)}</span>}
            {spec.destination?.arrive_by && <span className="chip">reach {spec.destination.label} by {fmtWhen(spec.destination.arrive_by)}</span>}
            {hc.min_rating && <span className="chip">≥ {hc.min_rating}★</span>}
            {hc.max_distance_km && <span className="chip">≤ {hc.max_distance_km} km</span>}
            {hc.must_include?.map((m: string) => <span key={m} className="chip">must: {m}</span>)}
            {spec.soft_preferences?.map((p: string) => <span key={p} className="chip">prefers {p}</span>)}
            {d.result?.identified_as && <span className="chip">📷 {d.result.identified_as}</span>}
          </div>
        )}
      </header>

      {d.status === "researching" && <TaskPlan d={d} />}
      {d.status === "researching" && <ResearchProgress d={d} />}
      {d.status === "failed" && (
        <>
          <ErrorNote error={`Research failed: ${d.error}`} />
          <button className="btn-ghost" onClick={() => api<Decision>(`/api/decisions/${d.id}/rerun`, { method: "POST" }).then((n) => router.push(`/decisions/${n.id}`))}>Retry</button>
        </>
      )}
      {spec.clarifying_question && ready && (
        <p className="rounded-lg bg-accent/10 px-3 py-2 text-sm">🤔 {spec.clarifying_question}</p>
      )}

      {ready && (
        <>
          {isErrands ? <ErrandsView d={d} /> : d.decision_type === "general" ? <ResearchView d={d} />
            : d.decision_type === "trip" ? <TripView d={d} /> : <Recommendation d={d} onChoose={choose} />}
          {d.decision_type === "video" && <LearningPath d={d} />}
          {d.decision_type === "knowledge" && <Landscape d={d} />}

          <TaskPlan d={d} />

          {!isResearch && (
            <section className="card">
              <div className="flex gap-1 border-b border-line px-3 pt-2">
                {TABS.filter(([t]) => !(isErrands && t === "why")).map(([t, label]) => (
                  <button key={t} onClick={() => setTab(t)}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent font-medium" : "border-transparent text-muted hover:text-ink"}`}>
                    {label}
                  </button>
                ))}
                <div className="ml-auto flex items-center gap-2 pb-1">
                  {d.status === "ready" && !isErrands && (
                    <button className="btn-ghost !py-1 !text-xs" onClick={() => api(`/api/decisions/${d.id}/accept`, { method: "POST" }).then(load)}>Accept</button>
                  )}
                  <button className="text-xs text-muted hover:text-ink"
                    onClick={() => api<Decision>(`/api/decisions/${d.id}/rerun`, { method: "POST" }).then((n) => router.push(`/decisions/${n.id}`))}>
                    Refresh research
                  </button>
                </div>
              </div>
              <div className="p-5">
                {tab === "plan" && <PlanPanel d={d} reload={load} />}
                {tab === "why" && <WhyPanel d={d} onWhatIf={whatIfPatch} />}
                {tab === "whatif" && <WhatIfPanel d={d} reload={load} />}
                {tab === "evidence" && <EvidencePanel d={d} onChoose={isErrands ? undefined : choose} />}
              </div>
            </section>
          )}

          <div>
            <p className="label mb-2">Follow up</p>
            <AskBar decisionId={d.id} placeholder="Ask a what-if, or e.g. “remind me tomorrow evening to order them”"
              onReply={(r) => { if (r.type === "whatif") setTab("whatif"); load(); }} />
          </div>
        </>
      )}
    </div>
  );
}
