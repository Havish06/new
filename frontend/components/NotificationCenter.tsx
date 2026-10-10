"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Intervention } from "@/lib/api";
import { runAction } from "@/lib/actions";

const POLL_MS = 15000;

/** Polls delivered interventions, shows in-app toasts and (if allowed) browser notifications. */
export default function NotificationCenter() {
  const router = useRouter();
  const [items, setItems] = useState<Intervention[]>([]);
  const [perm, setPerm] = useState<NotificationPermission | "unsupported">("default");
  const shown = useRef<Set<string>>(new Set());

  useEffect(() => {
    setPerm(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  const poll = useCallback(async () => {
    try {
      const rows = await api<Intervention[]>("/api/interventions?status=delivered&unseen=true&limit=10");
      const fresh = rows.filter((r) => !shown.current.has(r.id));
      if (!fresh.length) return;
      fresh.forEach((r) => shown.current.add(r.id));
      setItems((prev) => [...fresh, ...prev].slice(0, 4));
      if (typeof Notification !== "undefined" && Notification.permission === "granted" && document.hidden) {
        fresh.forEach((r) => new Notification(r.title, { body: r.message, tag: r.id }));
      }
      await api("/api/interventions/seen", { method: "POST", json: { ids: fresh.map((r) => r.id) } });
    } catch {
      /* backend offline — stay quiet */
    }
  }, []);

  useEffect(() => {
    poll();
    const t = setInterval(poll, POLL_MS);
    return () => clearInterval(t);
  }, [poll]);

  const close = (id: string) => setItems((prev) => prev.filter((p) => p.id !== id));

  return (
    <>
      {perm === "default" && (
        <button
          onClick={async () => setPerm(await Notification.requestPermission())}
          className="fixed bottom-4 left-4 z-40 hidden rounded-full border border-line bg-card px-3 py-1.5 text-xs text-muted shadow-sm hover:text-ink md:block"
        >
          Enable desktop notifications
        </button>
      )}
      <div className="fixed bottom-4 right-4 z-50 flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((iv) => (
          <div key={iv.id} className="card p-4 shadow-lg">
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium">{iv.title}</p>
              <button onClick={() => close(iv.id)} className="text-muted hover:text-ink" aria-label="close">✕</button>
            </div>
            <p className="mt-1 text-sm text-muted">{iv.message}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {iv.actions.map((a, i) => (
                <button
                  key={i}
                  className={i === 0 && a.type !== "dismiss" ? "btn-accent !py-1 !text-xs" : "btn-ghost !py-1 !text-xs"}
                  onClick={async () => {
                    close(iv.id);
                    try { await runAction(iv, a, router); } catch {}
                  }}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
