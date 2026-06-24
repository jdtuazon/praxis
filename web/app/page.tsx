"use client";

import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Report } from "@/components/Report";
import { Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import type { Example, ExecutionReport } from "@/lib/types";

export default function ConsolePage() {
  const [instruction, setInstruction] = useState("");
  const [examples, setExamples] = useState<Example[]>([]);
  const [report, setReport] = useState<ExecutionReport | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.examples().then(setExamples).catch(() => setExamples([]));
  }, []);

  async function run(text?: string) {
    const value = (text ?? instruction).trim();
    if (!value || running) return;
    setInstruction(value);
    setRunning(true);
    setError(null);
    try {
      const r = await api.run(value);
      setReport(r);
      requestAnimationFrame(() => reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The agent could not be reached.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <>
      <PageHeader title="Instruct the agent.">
        Describe a task in plain language. Praxis decomposes it, executes it against Linear, synthesizes
        any capability it’s missing, and records what it learns, so the next run is measurably better.
      </PageHeader>

      <div className="panel p-2">
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run();
          }}
          rows={3}
          placeholder="e.g. Roll up all issues into a triage digest grouped by priority"
          className="w-full resize-y bg-transparent px-3 py-2.5 text-[15px] text-text placeholder:text-faint focus:outline-none"
        />
        <div className="flex items-center justify-between gap-3 border-t border-line-soft px-3 pt-2.5">
          <span className="hidden font-mono text-2xs text-faint sm:inline">⌘↵ to run</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => run()}
              disabled={running || !instruction.trim()}
              className="inline-flex items-center gap-2 rounded-sm bg-iris px-4 py-2 text-sm font-medium text-bg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {running ? <Spinner /> : null}
              {running ? "Running" : "Run"}
              {!running && <span aria-hidden>→</span>}
            </button>
          </div>
        </div>
        {running && (
          <div className="relative mt-2 h-px overflow-hidden">
            <span className="absolute inset-y-0 w-1/3 animate-sweep bg-gradient-to-r from-transparent via-iris to-transparent" />
          </div>
        )}
      </div>

      {examples.length > 0 && (
        <div className="mt-4">
          <div className="label mb-2">try a demo instruction — run them in order to watch it learn</div>
          <div className="flex flex-col gap-1.5">
            {examples.map((ex, i) => (
              <button
                key={i}
                onClick={() => run(ex.instruction)}
                disabled={running}
                className="group flex items-center gap-3 rounded-sm border border-line-soft bg-surface/60 px-3 py-2 text-left transition hover:border-iris/30 hover:bg-iris/[0.04] disabled:opacity-50"
              >
                <span className="font-mono text-2xs text-faint">{String(i + 1).padStart(2, "0")}</span>
                <span className="text-sm text-dim group-hover:text-text">{ex.instruction}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="mt-6 rounded-sm border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad">
          {error}
        </div>
      )}

      <div ref={reportRef} className="mt-8 scroll-mt-8">
        {report ? <Report report={report} /> : !error && <EmptyState />}
      </div>
    </>
  );
}

function EmptyState() {
  const items = [
    ["Decomposition", "compound instructions become an ordered, dependency-aware plan"],
    ["Synthesis", "missing capabilities are built, schema-validated, tested, and registered at runtime"],
    ["Learning", "constraints learned from one run change the plan on the next — proven with numbers"],
    ["Safety", "partial failures are compensated; irreversible effects are surfaced, never hidden"],
  ];
  return (
    <div className="panel p-6">
      <div className="label mb-4">what you’ll see in the report</div>
      <div className="grid gap-px overflow-hidden rounded-sm bg-line sm:grid-cols-2">
        {items.map(([t, d]) => (
          <div key={t} className="bg-surface p-4">
            <div className="text-sm font-medium text-text">{t}</div>
            <div className="mt-1 text-2xs leading-relaxed text-faint">{d}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
