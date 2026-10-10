"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Today", icon: "◐" },
  { href: "/decide", label: "Decide", icon: "◆" },
  { href: "/decisions", label: "Decisions", icon: "≡" },
  { href: "/tasks", label: "Tasks", icon: "☐" },
  { href: "/calendar", label: "Calendar", icon: "▦" },
  { href: "/inbox", label: "Inbox", icon: "✉" },
  { href: "/memory", label: "Memory", icon: "◎" },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

export default function Nav() {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line px-4 py-6 md:flex">
        <Link href="/" className="mb-8 px-2">
          <span className="font-mono text-sm font-semibold tracking-tight">Decision<span className="text-accent">OS</span></span>
          <span className="mt-0.5 block text-[11px] text-muted">Don&apos;t search. Decide. Act.</span>
        </Link>
        <nav className="flex flex-col gap-0.5">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href}
              className={`flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm transition ${active(l.href) ? "bg-card font-medium shadow-sm ring-1 ring-line" : "text-muted hover:text-ink"}`}>
              <span className="w-4 text-center font-mono text-xs">{l.icon}</span>{l.label}
            </Link>
          ))}
        </nav>
      </aside>
      <nav className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-line bg-card/95 px-1 py-1.5 backdrop-blur md:hidden">
        {LINKS.slice(0, 6).map((l) => (
          <Link key={l.href} href={l.href} className={`flex flex-col items-center px-2 text-[10px] ${active(l.href) ? "text-accent" : "text-muted"}`}>
            <span className="font-mono text-base leading-5">{l.icon}</span>{l.label}
          </Link>
        ))}
      </nav>
    </>
  );
}
