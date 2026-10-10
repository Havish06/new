"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ago, api, TYPE_LABEL } from "@/lib/api";
import { Empty, Pill, Spinner } from "@/components/ui";

type Row = { id: string; query: string; decision_type: string; status: string; headline?: string; options?: number; created_at: string };

const TONE: Record<string, "muted" | "good" | "warn" | "bad" | "accent"> = {
  researching: "accent", ready: "warn", accepted: "good", planned: "good", failed: "bad",
};

export default function Decisions() {
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => { api<Row[]>("/api/decisions?limit=100").then(setRows); }, []);
  if (!rows) return <Spinner />;
  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">Decisions</h1>
        <Link href="/decide" className="btn-primary">New decision</Link>
      </header>
      {rows.length === 0 ? <Empty>No decisions yet.</Empty> : (
        <ul className="card divide-y divide-line">
          {rows.map((r) => (
            <li key={r.id}>
              <Link href={`/decisions/${r.id}`} className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-paper">
                <div className="min-w-0">
                  <p className="truncate font-medium">{r.query}</p>
                  <p className="truncate text-sm text-muted">{r.headline || TYPE_LABEL[r.decision_type] || ""}</p>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="hidden text-xs text-muted sm:inline">{ago(r.created_at)}</span>
                  <Pill tone={TONE[r.status] || "muted"}>{r.status}</Pill>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
