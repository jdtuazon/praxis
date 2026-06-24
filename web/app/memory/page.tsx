"use client";

import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Label, Pill, Section, Spinner, Tile } from "@/components/ui";
import { api } from "@/lib/api";
import type { MemoryState } from "@/lib/types";

const SOURCE_TONE = { builtin: "dim", synthesized: "iris" } as const;
const STATUS_TONE = { builtin: "dim", trusted: "ok", probationary: "warn", demoted: "bad" } as const;

export default function MemoryPage() {
  const [mem, setMem] = useState<MemoryState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.memory().then(setMem).catch(() => setMem(null));
  }, []);
  useEffect(load, [load]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      load();
    } finally {
      setBusy(false);
    }
  }

  const c = mem?.counts;
  return (
    <>
      <PageHeader title="What the agent knows.">
        Memory is structured knowledge, not a log: cached entity ids, enum facts, permission boundaries
        and plan-rewriting workflow rules, each read <em>before</em> acting. It persists across sessions
        and is what makes the next run different from the last.
      </PageHeader>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile value={c?.executions ?? "—"} label="executions" />
        <Tile value={c?.capabilities ?? "—"} label="capabilities" />
        <Tile value={c?.constraints ?? "—"} label="active constraints" tone="aqua" />
        <Tile value={c?.instructions ?? "—"} label="instructions seen" />
      </div>

      {!mem ? (
        <div className="panel flex items-center gap-2 p-5 text-sm text-faint">
          <Spinner /> loading memory…
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <Section title={`capabilities · ${mem.capabilities.length}`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="label border-b border-line-soft [&>th]:pb-2 [&>th]:pr-4 [&>th]:font-normal">
                    <th>name</th>
                    <th>kind</th>
                    <th>source</th>
                    <th>status</th>
                    <th>uses</th>
                    <th>success</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line-soft">
                  {mem.capabilities.map((cap) => (
                    <tr key={cap.name} className="[&>td]:py-2.5 [&>td]:pr-4 align-top">
                      <td>
                        <div className="font-mono text-[13px] text-text">{cap.name}</div>
                        <div className="mt-0.5 max-w-md text-2xs text-faint">{cap.description}</div>
                      </td>
                      <td className="text-2xs text-dim">{cap.kind}</td>
                      <td>
                        <Pill tone={SOURCE_TONE[cap.source as keyof typeof SOURCE_TONE] ?? "dim"}>{cap.source}</Pill>
                      </td>
                      <td>
                        <Pill tone={STATUS_TONE[cap.status as keyof typeof STATUS_TONE] ?? "dim"}>{cap.status}</Pill>
                      </td>
                      <td className="nums font-mono text-2xs text-dim">{cap.attempts}</td>
                      <td className="nums font-mono text-2xs text-dim">
                        {cap.success_rate == null ? "—" : `${Math.round(cap.success_rate * 100)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title={`learned constraints · ${mem.constraints.length}`}>
            {mem.constraints.length === 0 ? (
              <p className="text-sm text-faint">
                Nothing learned yet. Run an instruction that hits a platform rule (e.g. completing an
                issue that needs an estimate) and the constraint will appear here.
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-line-soft">
                {mem.constraints.map((con, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3">
                    <span className="font-mono text-[13px] text-text">
                      {con.scope}/{con.key}
                    </span>
                    <span className="font-mono text-2xs text-faint">{con.kind}</span>
                    <Pill tone={con.origin === "runtime_learned" ? "aqua" : "dim"}>
                      {con.origin === "runtime_learned" ? "learned" : "schema"}
                    </Pill>
                    {con.rewrites_plan && <Pill tone="iris">rewrites plan</Pill>}
                    <span className="ml-auto nums font-mono text-2xs text-faint">{con.hits} hits</span>
                    <div className="w-full text-2xs text-faint">{con.description}</div>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title="memory controls"
            aside={busy ? <Spinner /> : null}
          >
            <p className="mb-3 text-2xs leading-relaxed text-faint">
              Wiping <em>only</em> constraints is the negative control: it reverts learned behaviour while
              keeping capabilities and plans, proving the improvement was caused by memory.
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => act(api.wipeConstraints)}
                disabled={busy}
                className="rounded-sm border border-line px-3 py-1.5 text-sm text-dim transition hover:border-warn/40 hover:text-warn disabled:opacity-50"
              >
                Wipe constraints
              </button>
              <button
                onClick={() => {
                  if (confirm("Erase all learned memory (executions, capabilities, constraints)?")) act(api.reset);
                }}
                disabled={busy}
                className="rounded-sm border border-line px-3 py-1.5 text-sm text-dim transition hover:border-bad/40 hover:text-bad disabled:opacity-50"
              >
                Reset all memory
              </button>
            </div>
          </Section>
        </div>
      )}
    </>
  );
}
