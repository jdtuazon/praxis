"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Meta } from "@/lib/types";

const NAV = [
  { href: "/", label: "Console" },
  { href: "/learning", label: "Learning" },
  { href: "/memory", label: "Memory" },
  { href: "/capabilities", label: "Capabilities" },
  { href: "/about", label: "About" },
];

function Mark() {
  // A double-loop mark: action feeding memory feeding better action.
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden>
      <circle cx="13" cy="13" r="11.25" stroke="#7B8CFF" strokeWidth="1.5" opacity="0.35" />
      <path
        d="M7 15.5c1.8 2.6 4.4 3.6 6.8 2.6 3-1.2 3.6-4.7 1.3-6.3-1.9-1.3-4.4-.4-5.2 1.6-.9 2.3.6 4.9 3.4 5.4"
        stroke="#7B8CFF"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="18.6" cy="8.2" r="1.7" fill="#4FD0C8" />
    </svg>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [reachable, setReachable] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m);
        setReachable(true);
      })
      .catch(() => setReachable(false));
  }, []);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1320px] flex-col lg:flex-row">
      {/* Rail */}
      <aside className="shrink-0 border-b border-line lg:sticky lg:top-0 lg:h-screen lg:w-[256px] lg:border-b-0 lg:border-r">
        <div className="flex h-full flex-col gap-8 p-6">
          <Link href="/" className="flex items-center gap-2.5">
            <Mark />
            <div className="text-[17px] font-semibold tracking-tight leading-none">praxis</div>
          </Link>

          <nav className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
            {NAV.map((item) => {
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`group flex shrink-0 rounded-sm border px-3 py-2 transition-colors ${
                    active
                      ? "border-iris/30 bg-iris/[0.06]"
                      : "border-transparent hover:border-line hover:bg-white/[0.02]"
                  }`}
                >
                  <span className={`text-sm font-medium ${active ? "text-text" : "text-dim group-hover:text-text"}`}>
                    {item.label}
                  </span>
                </Link>
              );
            })}
          </nav>

          <div className="mt-auto hidden flex-col gap-3 lg:flex">
            <ModeBadge meta={meta} reachable={reachable} />
            <a
              className="label hover:text-dim"
              href="https://github.com/jdtuazon/watermelon"
              target="_blank"
              rel="noreferrer"
            >
              ↗ source
            </a>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-content px-6 py-8 lg:px-10 lg:py-12">{children}</div>
      </main>
    </div>
  );
}

function ModeBadge({ meta, reachable }: { meta: Meta | null; reachable: boolean | null }) {
  if (reachable === false) {
    return (
      <div className="rounded-sm border border-bad/30 bg-bad/5 px-3 py-2">
        <div className="label text-bad">backend offline</div>
        <div className="mt-1 text-2xs text-faint">start the API: praxis serve</div>
      </div>
    );
  }
  const live = meta?.mode === "live";
  return (
    <div className="rounded-sm border border-line bg-surface-2 px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-aqua" : "bg-warn"}`} />
        <span className="label">{live ? "live · real Linear" : "offline · simulation"}</span>
      </div>
      <div className="mt-1 text-2xs text-faint">
        {meta ? (live ? "real API calls" : "deterministic FakeLinear") : "connecting…"}
      </div>
    </div>
  );
}
