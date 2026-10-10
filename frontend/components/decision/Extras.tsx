"use client";
import { Decision } from "@/lib/api";
import { Spinner } from "../ui";

const STAGES = [
  ["understand", "Understanding your goal"],
  ["plan_research", "Planning what to do"],
  ["discover", "Finding destinations"],
  ["identify", "Identifying the image"],
  ["search", "Searching live sources"],
  ["evidence", "Collecting & verifying evidence"],
  ["judge", "Judging soft criteria"],
  ["decide", "Comparing options"],
  ["explain", "Explaining the decision"],
];

export function ResearchProgress({ d }: { d: Decision }) {
  const steps = d.research?.steps || [];
  const done = new Map(steps.map((s) => [s.stage, s]));
  const visible = STAGES.filter(([k]) => done.has(k) || !["identify", "judge", "discover"].includes(k));
  const nextIdx = visible.findIndex(([k]) => !done.has(k));
  return (
    <section className="card p-5">
      <p className="label mb-3">Agent loop</p>
      <ol className="space-y-2">
        {visible.map(([k, label], i) => {
          const s = done.get(k);
          const running = d.status === "researching" && i === nextIdx;
          return (
            <li key={k} className={`flex items-start gap-3 text-sm ${!s && !running ? "text-muted/60" : ""}`}>
              <span className="mt-0.5 w-4 text-center">{s ? (s.status === "failed" ? "✗" : "✓") : running ? <Spinner /> : "·"}</span>
              <div>
                <p className={s ? "" : running ? "font-medium" : ""}>{label}</p>
                {s && <p className="text-xs text-muted">{s.detail}</p>}
              </div>
            </li>
          );
        })}
        {done.get("error") && <li className="text-sm text-bad">✗ {done.get("error")!.detail}</li>}
      </ol>
    </section>
  );
}

export function LearningPath({ d }: { d: Decision }) {
  const items = d.result.learning_path || [];
  if (!items.length) return null;
  return (
    <section className="card p-5">
      <p className="label mb-3">{items.length}-day learning path</p>
      <ol className="space-y-3">
        {items.map((it: any, i: number) => (
          <li key={it.id} className="flex gap-4">
            <span className="font-mono text-sm text-muted">Day {i + 1}</span>
            <div>
              <a href={it.url} target="_blank" rel="noreferrer" className="font-medium hover:underline">{it.title}</a>
              <p className="text-xs text-muted">{[it.channel, it.length_min && `${Math.round(it.length_min)} min`, it.focus].filter(Boolean).join(" · ")}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-muted">Redundant videos were removed and the rest ordered from fundamentals to advanced. Create a plan to schedule one per evening.</p>
    </section>
  );
}

export function Landscape({ d }: { d: Decision }) {
  const l = d.result.landscape;
  if (!l || !Object.keys(l).length) return null;
  const cols: [string, string[]][] = [["Established", l.established || []], ["Emerging", l.emerging || []], ["Research gaps", l.gaps || []]];
  const byId = Object.fromEntries(d.candidates.map((c) => [c.id, c]));
  return (
    <section className="card p-5">
      <p className="label mb-3">Landscape</p>
      <div className="grid gap-4 md:grid-cols-3">
        {cols.map(([t, xs]) => (
          <div key={t}>
            <p className="font-medium">{t}</p>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-sm text-muted">{xs.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </div>
        ))}
      </div>
      <p className="label mb-2 mt-5">Directions considered</p>
      <ul className="space-y-3">
        {(d.result.ranking || []).map((r: any) => {
          const c = byId[r.id];
          return (
            <li key={r.id} className="rounded-lg border border-line p-3">
              <div className="flex justify-between gap-2"><p className="font-medium">{c?.name}</p><span className="font-mono text-sm">{r.score.toFixed(0)}</span></div>
              <p className="mt-1 text-sm text-muted">{c?.snippet}</p>
              {c?.attrs?.why_now && <p className="mt-1 text-sm">Why now: {c.attrs.why_now}</p>}
              {c?.attrs?.evidence?.length > 0 && (
                <p className="mt-1 text-xs text-muted">Evidence: {c.attrs.evidence.map((e: any, i: number) => (
                  <a key={i} href={e.url} target="_blank" rel="noreferrer" className="underline">{e.source}{i < c.attrs.evidence.length - 1 ? ", " : ""}</a>))}</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
