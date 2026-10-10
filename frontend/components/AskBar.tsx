"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, API } from "@/lib/api";
import { Spinner } from "./ui";

const EXAMPLES = [
  "I need a laptop for coding under ₹70,000, preferably lightweight, this week.",
  "I need to buy a USB drive, print my assignment, get passport photos and reach college by 4 PM. I have ₹1,000.",
  "Where should I repair my laptop?",
  "Cheapest way to get from Chennai to Bangalore this weekend under ₹3,000?",
  "I'm trying to learn Docker. What should I watch?",
  "Remind me to submit the assignment tomorrow at 6 PM",
];

export default function AskBar({ decisionId, onReply, showExamples = false, placeholder }:
  { decisionId?: string; onReply?: (r: any) => void; showExamples?: boolean; placeholder?: string }) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [showImage, setShowImage] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(f: File) {
    setError(null);
    const fd = new FormData();
    fd.append("file", f);
    const res = await fetch(`${API}/api/uploads`, { method: "POST", body: fd });
    const j = await res.json();
    if (!res.ok) throw new Error(j.detail || "Upload failed");
    setImageUrl(j.url);
    if (j.note) setError(j.note);
  }

  async function submit(message?: string) {
    const msg = (message ?? text).trim() || (imageUrl ? "What is this and where should I buy it?" : "");
    if (!msg) return;
    setBusy(true); setError(null); setReply(null);
    try {
      const r = await api<any>("/api/ask", { method: "POST", json: { message: msg, decision_id: decisionId, image_url: imageUrl || null } });
      if (r.type === "decision") {
        router.push(`/decisions/${r.decision.id}`);
        return;
      }
      setReply(r.reply);
      setText("");
      onReply?.(r);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="card p-2 focus-within:border-accent">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          rows={2}
          placeholder={placeholder || "What are you trying to figure out?"}
          className="w-full resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted"
        />
        {showImage && (
          <div className="flex items-center gap-2 px-2 pb-2">
            <input className="input !py-1.5" placeholder="Paste an image URL…" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} />
            <button className="btn-ghost !py-1.5 text-xs" onClick={() => fileRef.current?.click()}>Upload</button>
            <input ref={fileRef} type="file" accept="image/*" hidden
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0]).catch((er) => setError(er.message))} />
          </div>
        )}
        <div className="flex items-center justify-between px-1">
          <button onClick={() => setShowImage((v) => !v)} className="rounded-md px-2 py-1 text-xs text-muted hover:text-ink">
            {showImage ? "− image" : "+ image"}
          </button>
          <button onClick={() => submit()} disabled={busy} className="btn-primary !py-1.5">
            {busy ? <Spinner /> : decisionId ? "Ask" : "Decide →"}
          </button>
        </div>
      </div>
      {reply && <p className="mt-2 rounded-lg bg-good/10 px-3 py-2 text-sm text-good">{reply}</p>}
      {error && <p className="mt-2 rounded-lg bg-warn/10 px-3 py-2 text-sm text-warn">{error}</p>}
      {showExamples && (
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => { setText(ex); submit(ex); }}
              className="chip text-left hover:border-accent hover:text-ink">{ex}</button>
          ))}
        </div>
      )}
    </div>
  );
}
