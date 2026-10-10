"use client";
import { Decision, inr } from "@/lib/api";
import { WeightBar } from "../ui";

const ELIM_LABEL: Record<string, string> = {
  over_budget: "over budget", poor_reviews: "poor reviews", unavailable: "unavailable in time",
  too_far: "too far", closed: "closed now", missing_requirement: "missing a requirement",
};

function fmtRaw(label: string, raw: number | null) {
  if (raw == null) return "—";
  const l = label.toLowerCase();
  if (l === "price" || l === "cost") return inr(raw);
  if (l === "distance") return `${raw.toFixed(1)} km`;
  if (l === "review volume") return `${Math.round(10 ** raw - 1).toLocaleString("en-IN")} reviews`;
  if (l === "views" || l === "popularity") return `${Math.round(10 ** raw - 1).toLocaleString("en-IN")}`;
  if (l.includes("delivery") || l.includes("open")) return raw >= 0.99 ? "yes / today" : raw.toFixed(2);
  return Number.isInteger(raw) ? String(raw) : raw.toFixed(2);
}

export default function WhyPanel({ d, onWhatIf }: { d: Decision; onWhatIf: (patch: any, label: string) => void }) {
  const r = d.result;
  const stats = r.stats || {};
  const chosen = r.user_choice || r.winner;
  const row = r.ranking?.find((x: any) => x.id === chosen);
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div className="space-y-5">
        <div>
          <p className="label mb-2">Your priorities</p>
          <div className="space-y-2">
            {d.spec.criteria?.map((c: any) => <WeightBar key={c.key} label={c.label} weight={c.weight} />)}
          </div>
          <p className="mt-2 text-xs text-muted">Weights come from what you said ({d.spec.extracted_by}). The score means
            “best for <em>your stated</em> priorities”, not objective truth.</p>
        </div>
        <div className="grid grid-cols-3 gap-3">
          {[["options", stats.candidates], ["sources", stats.sources], ["reviews", stats.reviews?.toLocaleString("en-IN")]].map(([k, v]) => (
            <div key={k as string} className="rounded-lg border border-line p-3">
              <p className="font-mono text-xl">{v ?? "—"}</p><p className="text-xs text-muted">{k} researched</p>
            </div>
          ))}
        </div>
        {Object.keys(r.eliminated_summary || {}).length > 0 && (
          <div>
            <p className="label mb-1">Eliminated</p>
            <ul className="text-sm">
              {Object.entries(r.eliminated_summary).map(([k, n]) => <li key={k}>{n as number} {ELIM_LABEL[k] || k}</li>)}
            </ul>
          </div>
        )}
      </div>
      <div className="space-y-5">
        {row && (
          <div>
            <p className="label mb-2">How {row.name.length > 40 ? "the winner" : row.name} scored</p>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1 font-normal">Criterion</th><th className="font-normal">Value</th><th className="text-right font-normal">Points</th></tr></thead>
              <tbody>
                {Object.values(row.breakdown).map((b: any) => (
                  <tr key={b.label} className="border-t border-line">
                    <td className="py-1.5">{b.label}</td>
                    <td className="font-mono text-xs">{fmtRaw(b.label, b.raw)}</td>
                    <td className="text-right font-mono">{(b.contribution * 100).toFixed(1)}</td>
                  </tr>
                ))}
                <tr className="border-t border-line font-medium"><td className="py-1.5">Total</td><td /><td className="text-right font-mono">{row.score.toFixed(1)}</td></tr>
              </tbody>
            </table>
            {row.missing?.length > 0 && <p className="mt-1 text-xs text-warn">No data for: {row.missing.join(", ")} (scored as average)</p>}
          </div>
        )}
        {r.what_could_change?.length > 0 && (
          <div>
            <p className="label mb-2">What could change the recommendation</p>
            <ul className="space-y-2">
              {r.what_could_change.map((c: any, i: number) => (
                <li key={i} className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-sm">
                  <span>{c.condition} → <b>{c.winner_name}</b></span>
                  <button className="btn-ghost shrink-0 !py-1 !text-xs" onClick={() => onWhatIf(c.patch, c.condition)}>Try it</button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
