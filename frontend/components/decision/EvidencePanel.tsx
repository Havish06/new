"use client";
import { Decision, inr } from "@/lib/api";
import { Pill } from "../ui";

export default function EvidencePanel({ d, onChoose }: { d: Decision; onChoose?: (id: string) => void }) {
  const r = d.result;
  const scores: Record<string, number> = Object.fromEntries((r.ranking || []).map((x: any) => [x.id, x.score]));
  const elim: Record<string, string[]> = Object.fromEntries((r.eliminated || []).map((x: any) => [x.id, x.reasons]));
  const rows = [...d.candidates].sort((a, b) => (scores[b.id] ?? -1) - (scores[a.id] ?? -1));
  const calls = d.research?.calls || [];
  return (
    <div className="space-y-6">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-2 font-normal">Option</th>
              <th className="font-normal">Evidence by source</th>
              <th className="font-normal">Rating</th>
              <th className="text-right font-normal">Score</th>
              {onChoose && <th />}
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className={`border-t border-line align-top ${elim[c.id] ? "opacity-60" : ""}`}>
                <td className="max-w-[260px] py-2 pr-3">
                  {c.url ? <a className="hover:underline" href={c.url} target="_blank" rel="noreferrer">{c.name}</a> : c.name}
                  {c.subtask && <div className="text-xs text-muted">for: {c.subtask}</div>}
                  {elim[c.id] && <div className="mt-1 text-xs text-bad">{elim[c.id].join("; ")}</div>}
                  {c.estimated && <Pill tone="warn">estimate</Pill>}
                </td>
                <td className="pr-3 text-xs">
                  {c.facts.price?.values?.map((v, i) => (
                    <div key={i}><span className="font-mono">{inr(v.value)}</span> <span className="text-muted">{v.source}</span></div>
                  ))}
                  {c.facts.distance_km && <div className="font-mono">{c.facts.distance_km.value.toFixed(2)} km</div>}
                  {c.attrs?.duration_min && <div>{Math.round(c.attrs.duration_min)} min</div>}
                  {c.attrs?.delivery && <div className="text-muted">{c.attrs.delivery}</div>}
                  {c.judgements && Object.keys(c.judgements).length > 0 && (
                    <div className="text-muted">{Object.entries(c.judgements).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}/10`).join(" · ")}</div>
                  )}
                  {!c.facts.price && c.sources.length > 0 && <div className="text-muted">{c.sources.join(", ")}</div>}
                </td>
                <td className="text-xs">
                  {c.facts.rating ? <>
                    <span>{c.facts.rating.value}★</span>
                    <div className="text-muted">{c.facts.rating.reviews?.toLocaleString("en-IN")} reviews</div>
                  </> : "—"}
                </td>
                <td className="text-right font-mono">{scores[c.id] != null ? scores[c.id].toFixed(1) : "—"}</td>
                {onChoose && (
                  <td className="pl-2 text-right">
                    {!elim[c.id] && scores[c.id] != null && (
                      <button className="text-xs text-muted hover:text-accent" onClick={() => onChoose(c.id)}>choose</button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <p className="label mb-2">Searches performed ({calls.length})</p>
        <ul className="space-y-1 font-mono text-xs">
          {calls.map((c, i) => (
            <li key={i} className={c.ok ? "" : "text-bad"}>
              {c.ok ? "✓" : "✗"} {c.engine} · {Object.entries(c.params).filter(([k]) => ["q", "k", "_nkw", "search_query", "departure_id", "arrival_id", "outbound_date", "url", "ll"].includes(k)).map(([k, v]) => `${k}=${v}`).join(" ")}
              <span className="text-muted"> → {c.count} results{c.cached ? " (cached)" : ""}{c.error ? ` · ${c.error}` : ""}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
