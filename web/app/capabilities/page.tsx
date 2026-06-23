"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Label, Pill, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { CapabilityInfo, MemoryState } from "@/lib/types";

export default function CapabilitiesPage() {
  const [mem, setMem] = useState<MemoryState | null>(null);
  useEffect(() => {
    api.memory().then(setMem).catch(() => setMem(null));
  }, []);

  const builtin = mem?.capabilities.filter((c) => c.source === "builtin") ?? [];
  const synthesized = mem?.capabilities.filter((c) => c.source === "synthesized") ?? [];

  return (
    <>
      <PageHeader eyebrow="the agent’s alphabet" title="Capabilities.">
        Atomic operations ship as trusted built-ins. Anything compound — aggregation, digests, bulk
        edits — is <em>synthesized at runtime</em> as a composition of trusted pieces, tested before it’s
        trusted. Synthesized capabilities appear here as the agent invents them.
      </PageHeader>

      {!mem ? (
        <div className="panel flex items-center gap-2 p-5 text-sm text-faint">
          <Spinner /> loading…
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          <Group
            title={`synthesized at runtime · ${synthesized.length}`}
            empty="None yet. Ask the Console for something compound (e.g. a triage digest) and watch one appear."
            caps={synthesized}
          />
          <Group title={`built-in primitives · ${builtin.length}`} caps={builtin} />
        </div>
      )}
    </>
  );
}

const STATUS_TONE = { builtin: "dim", trusted: "ok", probationary: "warn", demoted: "bad" } as const;

function Group({ title, caps, empty }: { title: string; caps: CapabilityInfo[]; empty?: string }) {
  return (
    <section>
      <Label className="mb-3">{title}</Label>
      {caps.length === 0 ? (
        <div className="panel p-5 text-sm text-faint">{empty}</div>
      ) : (
        <div className="grid gap-px overflow-hidden rounded-md bg-line sm:grid-cols-2">
          {caps.map((c) => (
            <div key={c.name} className="bg-surface p-4">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13px] text-text">{c.name}</span>
                <span className="ml-auto">
                  <Pill tone={STATUS_TONE[c.status as keyof typeof STATUS_TONE] ?? "dim"}>{c.status}</Pill>
                </span>
              </div>
              <div className="mt-1.5 text-2xs leading-relaxed text-faint">{c.description}</div>
              <div className="mt-2 flex items-center gap-3 font-mono text-2xs text-faint">
                <span>{c.kind}</span>
                <span>·</span>
                <span>{c.attempts} uses</span>
                {c.success_rate != null && (
                  <>
                    <span>·</span>
                    <span className="text-dim">{Math.round(c.success_rate * 100)}% success</span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
