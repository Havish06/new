"use client";
import { ReactNode } from "react";

export function Section({ title, action, children, className = "" }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card p-5 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="label">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

export function ConfidenceBar({ label, value }: { label: string; value?: number }) {
  if (value == null) return null;
  const pct = Math.round(value * 100);
  const color = pct >= 85 ? "bg-good" : pct >= 65 ? "bg-warn" : "bg-bad";
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="w-28 shrink-0 text-muted">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right font-mono">{pct}%</span>
    </div>
  );
}

export function WeightBar({ label, weight }: { label: string; weight: number }) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-40 shrink-0 truncate">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
        <div className="h-full bg-accent" style={{ width: `${Math.round(weight * 100)}%` }} />
      </div>
      <span className="w-10 text-right font-mono text-xs">{Math.round(weight * 100)}%</span>
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex gap-1 ${className}`} aria-label="loading">
      {[0, 1, 2].map((i) => (
        <span key={i} className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" style={{ animationDelay: `${i * 0.2}s` }} />
      ))}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-muted">{children}</p>;
}

export function Stars({ value, reviews }: { value?: number | null; reviews?: number | null }) {
  if (value == null) return null;
  return (
    <span className="text-sm">
      <span className="text-warn">★</span> {value.toFixed(1)}
      {reviews != null && <span className="text-muted"> ({reviews.toLocaleString("en-IN")})</span>}
    </span>
  );
}

export function Pill({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "good" | "warn" | "bad" | "accent" }) {
  const map = {
    muted: "border-line text-muted",
    good: "border-good/40 text-good bg-good/5",
    warn: "border-warn/40 text-warn bg-warn/5",
    bad: "border-bad/40 text-bad bg-bad/5",
    accent: "border-accent/40 text-accent bg-accent/5",
  };
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${map[tone]}`}>{children}</span>;
}

export function ErrorNote({ error }: { error?: string | null }) {
  if (!error) return null;
  return <div className="rounded-lg border border-bad/40 bg-bad/5 px-3 py-2 text-sm text-bad">{error}</div>;
}
