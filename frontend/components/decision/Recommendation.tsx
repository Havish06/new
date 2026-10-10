"use client";
import { Candidate, Decision, inr } from "@/lib/api";
import { ConfidenceBar, Pill, Stars } from "../ui";

export function candidateLine(c: Candidate) {
  const bits: string[] = [];
  if (c.facts.price) bits.push(inr(c.facts.price.value));
  if (c.facts.distance_km) bits.push(`${c.facts.distance_km.value.toFixed(1)} km`);
  if (c.attrs?.duration_min) bits.push(`${Math.round(c.attrs.duration_min)} min`);
  if (c.attrs?.length_min) bits.push(`${Math.round(c.attrs.length_min)} min video`);
  if (c.attrs?.channel) bits.push(c.attrs.channel);
  if (c.attrs?.depart) bits.push(`dep ${String(c.attrs.depart).slice(-5)}`);
  if (c.open_state) bits.push(c.open_state);
  return bits.join(" · ");
}

export default function Recommendation({ d, onChoose }: { d: Decision; onChoose: (id: string) => void }) {
  const r = d.result;
  const exp = r.explanation || {};
  const byId = Object.fromEntries(d.candidates.map((c) => [c.id, c]));
  const chosenId = r.user_choice || r.winner;
  const w: Candidate | undefined = byId[chosenId];
  const top = r.ranking?.find((x: any) => x.id === chosenId);

  return (
    <div className="space-y-4">
      <section className="card overflow-hidden">
        <div className="border-b border-line bg-accent/5 px-5 py-4">
          <p className="label !text-accent">{r.user_choice ? "Your choice" : "Recommendation"}</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{exp.headline || w?.name || "No recommendation"}</h2>
          {exp.summary && <p className="mt-2 text-[15px] leading-relaxed">{exp.summary}</p>}
        </div>

        {w && (
          <div className="grid gap-6 p-5 md:grid-cols-[1.4fr_1fr]">
            <div className="space-y-3">
              <div>
                {w.url ? <a href={w.url} target="_blank" rel="noreferrer" className="text-lg font-medium hover:underline">{w.name}</a>
                  : <p className="text-lg font-medium">{w.name}</p>}
                <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted">
                  {w.best_offer && <span className="font-mono text-lg text-ink">{inr(w.best_offer.price)}</span>}
                  <Stars value={w.facts.rating?.value} reviews={w.facts.rating?.reviews} />
                  {w.address && <span>{w.address}</span>}
                  {top && <Pill tone="accent">score {top.score.toFixed(0)}/100</Pill>}
                </div>
                <p className="mt-1 text-sm text-muted">{candidateLine(w)}</p>
                {w.best_offer && <p className="mt-1 text-xs text-muted">Best price seen at {w.best_offer.source}</p>}
              </div>
              {exp.why?.length > 0 && (
                <ul className="space-y-1">
                  {exp.why.map((y: string, i: number) => <li key={i} className="flex gap-2 text-sm"><span className="text-good">✓</span>{y}</li>)}
                </ul>
              )}
              {exp.tradeoffs?.length > 0 && (
                <ul className="space-y-1">
                  {exp.tradeoffs.map((y: string, i: number) => <li key={i} className="flex gap-2 text-sm text-muted"><span>↔</span>{y}</li>)}
                </ul>
              )}
              {w.judgement_note && <p className="text-sm italic text-muted">“{w.judgement_note}”</p>}
            </div>
            <div className="space-y-2">
              <p className="label">Confidence</p>
              <ConfidenceBar label="Product identity" value={w.confidence?.identity} />
              <ConfidenceBar label="Price" value={w.confidence?.price} />
              <ConfidenceBar label="Review quality" value={w.confidence?.reviews} />
              <ConfidenceBar label="Judgement" value={w.confidence?.judgement} />
              <p className="pt-1 text-xs text-muted">Sources: {w.sources.join(", ")}</p>
            </div>
          </div>
        )}

        {(r.insights?.length > 0 || r.warnings?.length > 0 || r.notes?.length > 0) && (
          <div className="space-y-2 border-t border-line px-5 py-4">
            {r.insights?.map((x: any, i: number) => (
              <p key={i} className="rounded-lg bg-good/10 px-3 py-2 text-sm text-good">💡 {x.text}</p>
            ))}
            {r.warnings?.map((x: string, i: number) => (
              <p key={i} className="rounded-lg bg-warn/10 px-3 py-2 text-sm text-warn">⚠ {x}</p>
            ))}
            {r.notes?.map((x: string, i: number) => <p key={i} className="text-sm text-muted">{x}</p>)}
          </div>
        )}
      </section>

      {r.alternatives?.length > 0 && (
        <section>
          <p className="label mb-2">Alternatives</p>
          <div className="grid gap-3 md:grid-cols-3">
            {r.alternatives.map((a: any) => {
              const c = byId[a.id];
              return (
                <div key={a.id} className="card flex flex-col justify-between p-4">
                  <div>
                    <p className="label">{a.label}</p>
                    <p className="mt-1 line-clamp-2 font-medium">{a.name}</p>
                    {c && <p className="mt-1 text-sm text-muted">{candidateLine(c)}</p>}
                    {c && <Stars value={c.facts.rating?.value} reviews={c.facts.rating?.reviews} />}
                  </div>
                  <button className="btn-ghost mt-3 !py-1 !text-xs" onClick={() => onChoose(a.id)}>Choose this instead</button>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
