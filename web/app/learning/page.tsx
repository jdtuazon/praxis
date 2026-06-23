"use client";

import { useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Bar, Label, Pill, Section, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { BenchResult, BenchRow } from "@/lib/types";

export default function LearningPage() {
  const [data, setData] = useState<BenchResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setData(await api.bench());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not run the benchmark.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow="measurable self-improvement" title="Before / after, with a control.">
        The headline isn’t “it feels faster.” It’s a different decision, proven with numbers — and a
        negative control that reverts the gain when the learned constraint is wiped. Run it live.
      </PageHeader>

      <button
        onClick={run}
        disabled={running}
        className="mb-8 inline-flex items-center gap-2 rounded-sm bg-iris px-4 py-2 text-sm font-medium text-bg transition hover:brightness-110 disabled:opacity-50"
      >
        {running ? <Spinner /> : null}
        {running ? "Running benchmark…" : data ? "Re-run benchmark" : "Run benchmark"}
      </button>

      {error && (
        <div className="mb-6 rounded-sm border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad">{error}</div>
      )}

      {!data ? (
        <div className="panel p-6 text-sm text-faint">
          The benchmark runs the agent several times against a fresh memory and reports the real call
          counts for two independent learning mechanisms.
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <Section
            title="Mechanism A · a learned rule rewrites the plan (failure avoidance)"
            aside={<Pill tone="aqua">wasted calls → 0</Pill>}
          >
            <BenchScale
              metric="wasted_calls"
              rows={[
                ["run 1 · cold — rule unknown", data.workflow_rule.cold],
                ["run 2 · warm — rule learned, plan rewritten", data.workflow_rule.warm],
                ["run 3 · control — constraints wiped", data.workflow_rule.control_after_wipe],
              ]}
              unit="wasted calls"
            />
            <p className="mt-4 border-t border-line-soft pt-4 text-2xs leading-relaxed text-faint">
              The wasted call vanishes once the rule is learned — and <span className="text-warn">returns</span> when
              the constraint is wiped. The change is caused by memory, not luck or a cached answer.
            </p>
          </Section>

          <Section
            title="Mechanism B · runtime synthesis, then transfer"
            aside={<Pill tone="iris">0 re-synthesis</Pill>}
          >
            <BenchScale
              metric="api_calls"
              rows={[
                ["run 1 · cold — capability synthesized", data.synthesis_transfer.cold],
                ["run 2 · transfer — capability reused", data.synthesis_transfer.transfer],
              ]}
              unit="API calls"
            />
            <p className="mt-4 border-t border-line-soft pt-4 text-2xs leading-relaxed text-faint">
              A different, never-seen instruction pays <span className="text-aqua">no synthesis cost</span> — it reuses
              the capability built for a related task. Transfer a cache can’t fake.
            </p>
          </Section>
        </div>
      )}
    </>
  );
}

function BenchScale({
  rows,
  metric,
  unit,
}: {
  rows: [string, BenchRow][];
  metric: "wasted_calls" | "api_calls";
  unit: string;
}) {
  const max = Math.max(...rows.map(([, r]) => r[metric]), 1);
  return (
    <div className="flex flex-col gap-4">
      <Label>{unit}</Label>
      {rows.map(([label, r]) => {
        const v = r[metric];
        const tone = metric === "wasted_calls" ? (v === 0 ? "aqua" : "bad") : "iris";
        return (
          <div key={label} className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5">
            <span className="text-sm text-dim">{label}</span>
            <StatusPill status={r.status} />
            <div className="col-span-2 flex items-center gap-3">
              <Bar value={v} max={max} tone={tone} />
              <span
                className={`nums w-8 shrink-0 text-right font-mono text-sm ${
                  tone === "aqua" ? "text-aqua" : tone === "bad" ? "text-bad" : "text-text"
                }`}
              >
                {v}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone = status === "success" ? "ok" : status === "partial" ? "warn" : "iris";
  return <Pill tone={tone}>{status}</Pill>;
}
