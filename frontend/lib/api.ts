export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function api<T = any>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {};
  const res = await fetch(`${API}${path}`, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...(rest.headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

// ---------- types (mirroring the backend JSON) ----------
export type Fact = { value: number; values?: { source: string; value: number; url?: string; reviews?: number }[]; confidence?: number; reviews?: number; spread_pct?: number };

export type Candidate = {
  id: string; name: string; kind: string; url?: string; thumbnail?: string; sources: string[];
  facts: { price?: Fact; rating?: Fact; distance_km?: Fact };
  attrs: Record<string, any>; address?: string; open_state?: string; hours?: Record<string, string>;
  snippet?: string; best_offer?: { source: string; price: number; url?: string };
  confidence: Record<string, number>; warnings: string[]; judgements?: Record<string, number>;
  judgement_note?: string; estimated?: boolean; subtask?: string;
};

export type Criterion = { key: string; label: string; weight: number; direction: "min" | "max" };

export type RankRow = { id: string; name: string; score: number; missing: string[];
  breakdown: Record<string, { label: string; raw: number | null; norm: number; weight: number; contribution: number }> };

export type Scenario = { label: string; winner: string | null; winner_name: string; score?: number; changed?: boolean;
  note?: string; eliminated_summary?: Record<string, number>; at: string; result?: any };

export type Decision = {
  id: string; query: string; decision_type: string | null; status: string; error?: string;
  spec: any; result: any; candidates: Candidate[];
  research: { steps: { stage: string; detail: string; status: string; at: string }[]; plan: { need: string; capability: string }[];
    calls: { engine: string; params: Record<string, any>; ok: boolean; count: number; cached?: boolean; error?: string }[] };
  plan: { summary: string; steps: PlanStep[]; generated_by: string } | null;
  created_at: string; updated_at: string;
};

export type PlanStep = { title: string; start: string | null; duration_min: number; notes: string; kind: string; priority: string };

export type Task = { id: string; title: string; notes?: string; status: string; priority: string; deadline?: string;
  scheduled_start?: string; duration_min?: number; source_decision?: string; project?: string; reminder_at?: string; meta: any };

export type Intervention = { id: string; event_type: string; title: string; message: string; score: number;
  components: Record<string, any>; status: "delivered" | "suppressed"; reason: string;
  actions: { type: string; label: string; [k: string]: any }[]; seen: number; response?: string; created_at: string };

export type Memory = { id: string; kind: string; content: string; source: string; status: string; meta: any; created_at: string; updated_at: string };

// ---------- formatting ----------
export const inr = (v?: number | null) => (v == null ? "—" : "₹" + Math.round(v).toLocaleString("en-IN"));

export function fmtTime(iso?: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function fmtWhen(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const day = d.toDateString() === now.toDateString() ? "Today"
    : d.toDateString() === tomorrow.toDateString() ? "Tomorrow"
    : d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${fmtTime(iso)}`;
}

export function ago(iso?: string | null) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const TYPE_LABEL: Record<string, string> = {
  commerce: "Product decision", image: "Visual decision", local: "Local decision", errands: "Errand plan",
  travel: "Travel decision", trip: "Trip plan", knowledge: "Research decision", video: "Learning path", general: "Research",
};
