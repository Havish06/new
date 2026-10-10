"use client";
import { Decision, fmtTime, inr } from "@/lib/api";
import { Pill, Stars } from "../ui";

const KIND_DOT: Record<string, string> = { travel: "bg-muted", stop: "bg-accent", arrive: "bg-good", event: "bg-ink" };

export default function ErrandsView({ d }: { d: Decision }) {
  const r = d.result;
  const t = r.totals || {};
  return (
    <div className="space-y-4">
      <section className="card overflow-hidden">
        <div className="border-b border-line bg-accent/5 px-5 py-4">
          <p className="label !text-accent">Your plan</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{r.explanation?.headline}</h2>
          <p className="mt-1 text-sm text-muted">{r.explanation?.summary}</p>
        </div>
        <div className="grid grid-cols-2 divide-line border-b border-line md:grid-cols-5 md:divide-x">
          {[
            ["Total", inr(t.cost)],
            ["Locations", t.locations],
            ["Distance", `${t.distance_km} km`],
            ["Walking", `${t.walking_km} km`],
            ["Time", `~${Math.floor(t.duration_min / 60) ? `${Math.floor(t.duration_min / 60)}h ` : ""}${t.duration_min % 60}m`],
          ].map(([k, v]) => (
            <div key={k as string} className="px-5 py-3"><p className="font-mono text-lg">{v as any}</p><p className="text-xs text-muted">{k}</p></div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 px-5 py-3 text-sm">
          {r.within_budget === true && <Pill tone="good">✓ Within {inr(r.budget)} budget</Pill>}
          {r.within_budget === false && <Pill tone="bad">✗ Over {inr(r.budget)} budget</Pill>}
          <span className="text-muted">Goods {inr(t.goods)} · Transport {inr(t.transport)}</span>
        </div>
        {r.warnings?.length > 0 && (
          <div className="space-y-2 border-t border-line px-5 py-3">
            {r.warnings.map((w: string, i: number) => <p key={i} className="rounded-lg bg-warn/10 px-3 py-2 text-sm text-warn">⚠ {w}</p>)}
          </div>
        )}
      </section>

      <div className="grid gap-4 md:grid-cols-[1fr_1.2fr]">
        <section className="card p-5">
          <p className="label mb-3">Timeline</p>
          <ol className="relative space-y-4 border-l border-line pl-5">
            {r.timeline?.map((item: any, i: number) => (
              <li key={i} className="relative">
                <span className={`absolute -left-[25px] top-1.5 h-2.5 w-2.5 rounded-full ${KIND_DOT[item.kind] || "bg-muted"}`} />
                <p className="font-mono text-sm">{fmtTime(item.time)}</p>
                <p className="font-medium">{item.title}</p>
                {item.detail && <p className="text-xs text-muted">{item.detail}</p>}
              </li>
            ))}
          </ol>
        </section>
        <section className="space-y-3">
          {r.stops?.map((s: any, i: number) => (
            <div key={i} className="card p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="label">{i + 1}. {s.subtask}</p>
                  <p className="mt-1 font-medium">{s.place.url ? <a href={s.place.url} target="_blank" rel="noreferrer" className="hover:underline">{s.place.name}</a> : s.place.name}</p>
                  <p className="text-xs text-muted">{s.place.address}</p>
                </div>
                <span className="font-mono">{inr(s.cost)}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
                <Stars value={s.place.rating} reviews={s.place.reviews} />
                {s.place.distance_km != null && <span className="text-muted">{s.place.distance_km.toFixed(1)} km from start</span>}
                {s.closes && <span className="text-muted">closes {s.closes}</span>}
                {s.hours_ok === false && <Pill tone="bad">may be closed</Pill>}
              </div>
              {s.alternatives?.length > 0 && (
                <p className="mt-2 text-xs text-muted">Backups: {s.alternatives.map((a: any) => `${a.name}${a.rating ? ` (${a.rating}★)` : ""}`).join(" · ")}</p>
              )}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
