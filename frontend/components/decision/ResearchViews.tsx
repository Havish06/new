"use client";
import { Decision, inr } from "@/lib/api";
import { Pill, Stars } from "../ui";

const TOOL_LABEL: Record<string, string> = {
  ai_answer: "Google AI Mode", web_search: "Google Search + AI Overview", web_search_alt: "Bing", forum_search: "Forums", news_search: "Google News",
  product_search: "Shopping + Amazon", local_places: "Google Maps", directions: "Maps Directions", flights: "Google Flights",
  stays: "Google Hotels + Airbnb", tripadvisor: "Tripadvisor", events: "Google Events", jobs: "Google Jobs",
  videos: "YouTube", images: "Google Images", scholar: "Scholar + Patents", trends: "Google Trends",
  finance: "Google Finance", apps: "Play Store + App Store", ai_answer_alt: "Bing Copilot",
  web_search_more: "DuckDuckGo + Yahoo", news_alt: "Bing News", place_reviews: "Google Maps reviews",
  hotel_reviews: "Google Hotels reviews", markets: "Google Finance Markets", trending_now: "Google Trends (now)",
  explore_destinations: "Google Travel Explore",
  research_product: "Shopping + Amazon", search_web: "Google Search", find_local_places: "Google Maps",
  research_travel: "Flights + web", analyze_image: "Google Lens", research_academic: "Scholar + Patents",
  research_video: "YouTube",
};

const STATUS: Record<string, { label: string; tone: "muted" | "good" | "warn" | "bad" | "accent" }> = {
  planned: { label: "planned", tone: "muted" }, done: { label: "done", tone: "good" },
  empty: { label: "no results", tone: "warn" }, failed: { label: "failed", tone: "bad" },
  fallback: { label: "used fallback", tone: "accent" },
};

/** "Here's what I'll do" — the plan DecisionOS derived from the query, with live task status. */
export function TaskPlan({ d }: { d: Decision }) {
  const p = (d.research as any)?.task_plan;
  if (!p?.tasks?.length) return null;
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="label">Here's what I'll do</p>
        <span className="text-xs text-muted">planned by {p.planned_by}</span>
      </div>
      {p.summary && <p className="mt-2 text-[15px]">{p.summary}</p>}
      <ol className="mt-3 space-y-2">
        {p.tasks.map((t: any, i: number) => {
          const st = STATUS[t.status] || STATUS.planned;
          return (
            <li key={t.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="w-5 font-mono text-muted">{i + 1}.</span>
              <span className="min-w-0 flex-1">{t.purpose}</span>
              <span className="text-xs text-muted">{TOOL_LABEL[t.tool] || t.tool}{t.fallback ? ` → ${TOOL_LABEL[t.fallback] || t.fallback}` : ""}</span>
              {d.status !== "researching" || t.status !== "planned"
                ? <Pill tone={st.tone}>{st.label}{t.count != null ? ` · ${t.count}` : ""}</Pill> : null}
            </li>
          );
        })}
      </ol>
      {p.assumptions?.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted">{p.assumptions.map((a: string, i: number) => <li key={i}>Assumption: {a}</li>)}</ul>
      )}
    </section>
  );
}

function ItemCard({ it }: { it: any }) {
  const a = it.attrs || {};
  const price = it.price != null ? inr(it.price) : a.total_price ? `${inr(a.total_price)} total` : null;
  return (
    <li className="flex gap-3 rounded-lg border border-line p-3">
      {it.kind === "image" && it.thumbnail && <img src={it.thumbnail} alt="" className="h-16 w-24 shrink-0 rounded object-cover" />}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          {it.url ? <a href={it.url} target="_blank" rel="noreferrer" className="font-medium hover:underline">{it.name}</a>
            : <p className="font-medium">{it.name}</p>}
          <span className="font-mono text-xs text-muted">[{it.n}]</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
          {price && <span className="text-ink">{price}</span>}
          <Stars value={typeof it.rating === "number" ? it.rating : null} reviews={typeof it.reviews === "number" ? it.reviews : null} />
          {a.when && <span>{a.when}</span>}
          {a.venue && <span>{a.venue}</span>}
          {a.change_pct != null && <span className={a.movement === "Down" ? "text-bad" : "text-good"}>{a.movement === "Down" ? "▼" : "▲"} {a.change_pct}%</span>}
          {a.direction && a.latest != null && <span>{a.direction} · latest {a.latest}, peak {a.peak}</span>}
          {a.increase_pct != null && <span>+{a.increase_pct}%{a.search_volume ? ` · ${Number(a.search_volume).toLocaleString("en-IN")} searches` : ""}</span>}
          {a.date && it.kind !== "event" && <span>{a.date}</span>}
          {a.flight_price && <span>flights {inr(a.flight_price)}</span>}
          {a.topics && <span>topics: {a.topics.join(", ")}</span>}
          {a.developer && <span>{a.developer}</span>}
          {a.location && <span>{a.location}</span>}
          {it.address && <span className="truncate">{it.address}</span>}
          <span>{it.source}</span>
          {it.status !== "search result" && <Pill>{it.status}</Pill>}
        </div>
        {it.snippet && <p className="mt-1 line-clamp-2 text-sm text-muted">{it.snippet}</p>}
      </div>
    </li>
  );
}

/** Open-ended questions: the answer (written only from evidence) + the evidence, grouped by task. */
export function ResearchView({ d }: { d: Decision }) {
  const r = d.result || {};
  const a = r.answer;
  return (
    <div className="space-y-4">
      {a && (
        <section className="card overflow-hidden">
          <div className="border-b border-line bg-accent/5 px-5 py-4">
            <p className="label !text-accent">Answer</p>
            <p className="mt-2 whitespace-pre-line text-[15px] leading-relaxed">{a.text}</p>
            <p className="mt-3 text-xs text-muted">
              {a.generated_by === "claude" ? "Written by Claude from the evidence below. Numbers in [ ] point to the sources."
                : a.generated_by === "google_ai_mode" ? "Written by Google AI Mode (AI-generated) — check the sources and live data below."
                : "Showing the strongest evidence directly. Numbers in [ ] point to the sources."}
            </p>
          </div>
        </section>
      )}
      {(r.sections || []).filter((s: any) => s.items.length).map((s: any) => (
        <section key={s.task} className="card p-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <p className="label">{s.title}</p>
            <span className="text-xs text-muted">{TOOL_LABEL[s.tool] || s.tool}{s.fallback ? ` → ${TOOL_LABEL[s.fallback] || s.fallback}` : ""}</span>
          </div>
          <ul className="space-y-2">{s.items.map((it: any) => <ItemCard key={it.n} it={it} />)}</ul>
        </section>
      ))}
    </div>
  );
}

/** Trip planner: recommended destination, cost breakdown per option, itinerary. */
export function TripView({ d }: { d: Decision }) {
  const r = d.result || {};
  const exp = r.explanation || {};
  const t = r.trip || {};
  const options: any[] = r.options || [];
  const best = options.find((o) => o.name === r.winner);
  return (
    <div className="space-y-4">
      <section className="card overflow-hidden">
        <div className="border-b border-line bg-accent/5 px-5 py-4">
          <p className="label !text-accent">Recommendation</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">{exp.headline}</h2>
          {exp.summary && <p className="mt-2 text-[15px] leading-relaxed">{exp.summary}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <span className="chip">{t.days} days · {t.check_in} → {t.check_out}</span>
            <span className="chip">{t.travellers} {t.travellers === 1 ? "person" : "people"}</span>
            {t.origin && <span className="chip">from {t.origin}</span>}
            {t.max_km && <span className="chip">≤ {t.max_km} km</span>}
          </div>
        </div>
        {exp.why?.length > 0 && (
          <ul className="space-y-1 px-5 py-4 text-sm">{exp.why.map((w: string, i: number) => <li key={i}>✓ {w}</li>)}</ul>
        )}
      </section>

      {best?.how_to_get_there?.length > 0 && (
        <section className="card p-5">
          <p className="label mb-3">Getting to {best.name}</p>
          <ul className="space-y-2">
            {best.how_to_get_there.map((t: any, i: number) => (
              <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 rounded-lg border border-line p-3 text-sm">
                <span className="font-medium">{t.label}</span>
                <span className="font-mono">
                  {t.cost_low != null ? `${inr(t.cost_low)}–${inr(t.cost_high)}` : "fare not stated"}
                  {t.per_vehicle ? " per vehicle" : " per person"}{t.hours ? ` · ~${t.hours} h` : ""}
                </span>
                {t.detail && <p className="w-full text-muted">{t.detail}</p>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">From Google AI Mode — typical fares, not live availability.</p>
        </section>
      )}

      {best && r.itinerary?.length > 0 && (
        <section className="card p-5">
          <p className="label mb-3">{best.name} — day by day
            <span className="ml-2 normal-case tracking-normal text-muted">
              ({r.itinerary_by === "google_ai_mode" ? "from Google AI Mode" : r.itinerary_by === "claude" ? "by Claude" : "draft"})
            </span>
          </p>
          <ol className="space-y-3">
            {r.itinerary.map((day: any) => (
              <li key={day.day} className="flex gap-4">
                <span className="w-14 shrink-0 font-mono text-sm text-muted">Day {day.day}</span>
                <div>
                  <p className="font-medium">{day.title}</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm text-muted">{day.items.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
                </div>
              </li>
            ))}
          </ol>
          {r.guide_sources?.length > 0 && (
            <p className="mt-3 text-xs text-muted">Sources: {r.guide_sources.map((g: any, i: number) => (
              <a key={i} href={g.url} target="_blank" rel="noreferrer" className="underline">{g.source || g.title}{i < r.guide_sources.length - 1 ? ", " : ""}</a>))}</p>
          )}
        </section>
      )}

      <section className="card p-5">
        <p className="label mb-3">Destinations compared</p>
        <ul className="space-y-3">
          {options.map((o) => (
            <li key={o.name} className={`rounded-lg border p-4 ${o.name === r.winner ? "border-accent" : "border-line"} ${o.eliminated.length ? "opacity-70" : ""}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-lg font-medium">{o.name}</p>
                <p className="font-mono">{inr(o.total)}{o.missing_costs.length ? "+" : ""}</p>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
                {o.distance_km != null && <span>~{o.distance_km} km ({o.distance_basis})</span>}
                <span>transport {inr(o.costs.transport)} ({o.transport_basis ? "AI Mode fare" : "est."})</span>
                {o.travel_hours && <span>~{o.travel_hours} h drive</span>}
                <span>stay {inr(o.costs.stay)}</span>
                <span>food {inr(o.costs.food)} (est.)</span>
                <span>local {inr(o.costs.local)} (est.)</span>
              </div>
              {o.stay && (
                <p className="mt-2 text-sm">
                  Stay: {o.stay.url ? <a href={o.stay.url} target="_blank" rel="noreferrer" className="underline">{o.stay.name}</a> : o.stay.name}
                  {" "}— {inr(o.stay.price_per_night)}/night × {o.stay.nights}{o.stay.rooms > 1 ? ` × ${o.stay.rooms} rooms` : ""}
                  {o.stay.rating ? ` · ${o.stay.rating}★` : ""} <Pill>{o.stay.status}</Pill>
                </p>
              )}
              {o.stay?.guest_reviews?.length > 0 && (
                <ul className="mt-2 space-y-1 border-l-2 border-line pl-3 text-sm text-muted">
                  {o.stay.guest_reviews.map((g: any, i: number) => (
                    <li key={i}>“{g.text.slice(0, 220)}{g.text.length > 220 ? "…" : ""}”{g.rating ? ` — ${g.rating}★` : ""}{g.date ? `, ${g.date}` : ""}</li>
                  ))}
                </ul>
              )}
              {o.attractions.length > 0 && (
                <p className="mt-1 text-sm text-muted">Things to do: {o.attractions.slice(0, 5).map((a: any) => a.name).join(" · ")}</p>
              )}
              {o.eliminated.map((e: string) => <p key={e} className="mt-1 text-sm text-bad">✗ {e}</p>)}
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">Distances are Google Maps driving routes; hotel rates are the lowest listed for your dates; the chosen place's fare is from Google AI Mode; other costs are estimates. Confirm availability before booking.</p>
      </section>
    </div>
  );
}
