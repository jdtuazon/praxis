import type { ExecutionReport, StepReport, SynthesisResult } from "@/lib/types";
import { Markdown } from "./Markdown";
import { Bar, Delta, Label, Pill, Section, STATUS_TONE, Tile } from "./ui";

const STEP_GLYPH: Record<string, string> = {
  success: "✓",
  failed: "✕",
  skipped: "⊘",
  rolled_back: "↩",
  pending: "·",
  running: "▸",
};

const STATUS_LABEL: Record<string, string> = {
  success: "Success",
  partial: "Partial",
  failed: "Failed",
  rolled_back: "Rolled back",
};

const STRIPE: Record<string, string> = {
  success: "bg-ok",
  partial: "bg-warn",
  failed: "bg-bad",
  rolled_back: "bg-iris",
};

export function Report({ report }: { report: ExecutionReport }) {
  const L = report.learning;
  const hasBaseline = L.baseline_api_calls != null;
  return (
    <div className="flex flex-col gap-5">
      <StatusHeader report={report} />
      <Outputs steps={report.steps} />
      <StepTimeline steps={report.steps} />
      {report.synthesis.length > 0 && <SynthesisTrace results={report.synthesis} />}
      {report.decisions.length > 0 && <Decisions report={report} />}
      {(report.rollback_performed || report.manual_cleanup_required.length > 0) && (
        <Rollback report={report} />
      )}
      <LearningSignal report={report} hasBaseline={hasBaseline} />
      <MemoryDelta report={report} />
    </div>
  );
}

function StatusHeader({ report }: { report: ExecutionReport }) {
  const tone = STATUS_TONE[report.status] ?? "dim";
  const L = report.learning;
  return (
    <section className="panel relative animate-fade-up overflow-hidden">
      <span className={`absolute left-0 top-0 h-full w-1 ${STRIPE[report.status]}`} aria-hidden />
      <div className="flex flex-col gap-5 p-5 pl-6">
        <div className="flex flex-wrap items-center gap-3">
          <Pill tone={tone}>{STATUS_LABEL[report.status] ?? report.status}</Pill>
          <span className="text-sm text-dim">{report.summary}</span>
          <span className="ml-auto font-mono text-2xs text-faint">
            plan: {report.plan.source} · {report.confidence.toFixed(2)} confidence ·{" "}
            {report.duration_s.toFixed(3)}s
          </span>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile value={report.total_api_calls} label="API calls" />
          <Tile
            value={report.wasted_calls}
            label="wasted calls"
            tone={report.wasted_calls ? "bad" : "ok"}
          />
          <Tile value={report.total_llm_calls} label="LLM calls" />
          {L.wasted_calls_saved > 0 ? (
            <Tile value={<Delta value={L.wasted_calls_saved} />} label="wasted saved vs run 1" tone="aqua" emphasize />
          ) : report.synthesized_capabilities.length > 0 ? (
            <Tile value={report.synthesized_capabilities.length} label="capabilities synthesized" tone="iris" emphasize />
          ) : (
            <Tile value={`${Math.round(report.confidence * 100)}%`} label="confidence" />
          )}
        </div>
      </div>
    </section>
  );
}

function titleOf(s: StepReport): string {
  // "title=Issue digest by priority" / "identifier=ENG-3" → the human part.
  const m = /^[a-z_]+=(.*)$/i.exec(s.result_summary ?? "");
  return (m ? m[1] : s.result_summary) || s.intent;
}

function Outputs({ steps }: { steps: StepReport[] }) {
  // The concrete artifacts a run produced — so "success" is something you can
  // open and read, not just a status. Any entity the agent created or changed
  // carries a deep link; documents additionally render their content.
  const artifacts = steps.filter((s) => s.result_url);
  if (artifacts.length === 0) return null;
  return (
    <Section title="Outputs · what the run produced">
      <div className="flex flex-col gap-4">
        {artifacts.map((s) => (
          <article
            key={s.index}
            className="overflow-hidden rounded-md border border-line-soft bg-surface-2"
          >
            <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line-soft px-4 py-3">
              <span className="flex h-5 w-5 items-center justify-center rounded-sm bg-iris/10 text-2xs text-iris" aria-hidden>
                ▦
              </span>
              <span className="text-sm font-medium text-text">{titleOf(s)}</span>
              {s.capability && <span className="font-mono text-2xs text-faint">{s.capability}</span>}
              <a
                href={s.result_url!}
                target="_blank"
                rel="noreferrer"
                className="link ml-auto text-2xs"
              >
                open in Linear ↗
              </a>
            </header>
            {s.result_detail && (
              <div className="max-h-96 overflow-auto px-5 py-4">
                <Markdown source={s.result_detail} />
              </div>
            )}
          </article>
        ))}
      </div>
    </Section>
  );
}

function StepTimeline({ steps }: { steps: StepReport[] }) {
  return (
    <Section title="Execution · plan steps">
      <ol className="flex flex-col">
        {steps.map((s, i) => {
          const tone = STATUS_TONE[s.status] ?? "dim";
          const toneText =
            tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : tone === "iris" ? "text-iris" : "text-faint";
          const last = i === steps.length - 1;
          return (
            <li key={s.index} className="relative flex gap-4 pb-5 last:pb-0">
              {!last && <span className="absolute left-[11px] top-7 h-[calc(100%-1.25rem)] w-px bg-line" aria-hidden />}
              <span
                className={`relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-surface text-xs ${toneText} border-line`}
              >
                {STEP_GLYPH[s.status] ?? "·"}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm text-text">{s.intent}</span>
                  {s.capability && (
                    <span className="font-mono text-2xs text-iris">{s.capability}</span>
                  )}
                  {s.inserted_by_constraint && (
                    <Pill tone="iris">↻ inserted by learned rule</Pill>
                  )}
                  <span className="ml-auto nums font-mono text-2xs text-faint">
                    {s.api_calls} API
                    {s.wasted_calls ? <span className="text-bad"> · {s.wasted_calls} wasted</span> : null}
                  </span>
                </div>
                {(s.result_summary || s.error) && (
                  <div className={`mt-1 text-2xs ${s.error ? "text-bad/90" : "text-faint"}`}>
                    {s.error || s.result_summary}
                    {s.result_url && (
                      <a
                        href={s.result_url}
                        target="_blank"
                        rel="noreferrer"
                        className="link ml-2"
                      >
                        ↗ open
                      </a>
                    )}
                  </div>
                )}
                {s.provenance.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {s.provenance.map((p, j) => (
                      <span
                        key={j}
                        title={`${p.detail} (${p.ref})`}
                        className="rounded-sm border border-line-soft bg-surface-2 px-1.5 py-0.5 font-mono text-2xs text-dim"
                      >
                        {p.kind}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Section>
  );
}

function SynthesisTrace({ results }: { results: SynthesisResult[] }) {
  return (
    <Section title="Capability synthesis · reason → build → test → register">
      <div className="flex flex-col gap-4">
        {results.map((sy, i) => (
          <div key={i} className="rounded-sm border border-line-soft bg-surface-2 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <Pill tone={sy.success ? "ok" : "bad"}>{sy.success ? "registered" : "failed"}</Pill>
              {sy.capability_name && (
                <span className="font-mono text-sm text-iris">{sy.capability_name}</span>
              )}
              <span className="ml-auto nums font-mono text-2xs text-faint">
                {sy.api_calls} API · {sy.llm_calls} LLM
              </span>
            </div>
            <div className="mt-2 text-2xs text-faint">gap: {sy.requested_for}</div>
            <div className="mt-3 flex flex-col gap-2">
              {sy.attempts.map((a) => (
                <div key={a.attempt} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-2xs text-faint">attempt {a.attempt}</span>
                  {a.outcomes.map((o, j) => (
                    <span
                      key={j}
                      title={o.detail}
                      className={`rounded-sm border px-1.5 py-0.5 font-mono text-2xs ${
                        o.passed ? "border-ok/30 text-ok" : "border-bad/30 text-bad"
                      }`}
                    >
                      {o.passed ? "✓" : "✕"} {o.tier}
                      {o.api_calls ? ` (${o.api_calls})` : ""}
                    </span>
                  ))}
                  {a.error && <span className="text-2xs text-bad/80">{a.error}</span>}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Decisions({ report }: { report: ExecutionReport }) {
  return (
    <Section title="Decisions & rationale">
      <ul className="flex flex-col gap-3">
        {report.decisions.map((d, i) => (
          <li key={i} className="flex gap-3">
            <span className="mt-1 font-mono text-2xs uppercase tracking-label text-iris">{d.stage}</span>
            <div className="min-w-0">
              <div className="text-sm text-text">{d.summary}</div>
              {d.rationale && <div className="mt-0.5 text-2xs text-faint">{d.rationale}</div>}
            </div>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Rollback({ report }: { report: ExecutionReport }) {
  return (
    <Section title="Rollback · best-effort compensation">
      <div className="flex flex-col gap-2">
        {report.rollback_steps.map((r, i) => (
          <div key={i} className="flex items-center gap-2 text-sm text-iris">
            <span aria-hidden>↩</span> compensated: {r}
          </div>
        ))}
        {report.manual_cleanup_required.map((m, i) => (
          <div key={i} className="flex items-center gap-2 text-sm text-warn">
            <span aria-hidden>⚠</span> manual cleanup: {m}
          </div>
        ))}
      </div>
    </Section>
  );
}

function LearningSignal({ report, hasBaseline }: { report: ExecutionReport; hasBaseline: boolean }) {
  const L = report.learning;
  const max = Math.max(L.api_calls, L.baseline_api_calls ?? 0, 1);
  return (
    <Section
      title="Learning signal · this run vs first run of this intent"
      aside={<Pill tone={L.mode === "fresh" ? "dim" : "aqua"}>{L.mode}</Pill>}
    >
      <div className="mb-4 font-mono text-2xs text-faint">
        run #{L.run_number} · <span className="text-dim">{L.instruction_signature}</span>
      </div>

      {hasBaseline ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <CompareRow label="API calls" now={L.api_calls} base={L.baseline_api_calls!} max={max} />
          <CompareRow
            label="wasted calls"
            now={L.wasted_calls}
            base={L.baseline_wasted_calls!}
            max={Math.max(L.wasted_calls, L.baseline_wasted_calls ?? 0, 1)}
            invert
          />
        </div>
      ) : (
        <div className="rounded-sm border border-line-soft bg-surface-2 px-4 py-3 text-sm text-faint">
          First encounter with this intent — nothing to compare yet. Run a related instruction to see
          the agent transfer what it learned.
        </div>
      )}

      {L.attributions.length > 0 && (
        <ul className="mt-4 flex flex-col gap-1.5 border-t border-line-soft pt-4">
          {L.attributions.map((a, i) => (
            <li key={i} className="flex gap-2 text-2xs text-aqua">
              <span aria-hidden>→</span>
              <span className="text-dim">{a}</span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function CompareRow({
  label,
  now,
  base,
  max,
  invert = false,
}: {
  label: string;
  now: number;
  base: number;
  max: number;
  invert?: boolean;
}) {
  const saved = base - now;
  const good = invert ? saved > 0 : saved >= 0;
  return (
    <div className="rounded-sm border border-line-soft bg-surface-2 p-4">
      <div className="flex items-baseline justify-between">
        <Label>{label}</Label>
        <span className="nums font-mono text-2xs">
          {saved > 0 ? <span className="text-aqua">−{saved} saved</span> : <span className="text-faint">no change</span>}
        </span>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        <div className="flex items-center gap-3">
          <span className="w-12 shrink-0 text-2xs text-faint">run 1</span>
          <Bar value={base} max={max} tone="bad" />
          <span className="nums w-6 shrink-0 text-right font-mono text-2xs text-dim">{base}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-12 shrink-0 text-2xs text-faint">now</span>
          <Bar value={now} max={max} tone={good ? "aqua" : "iris"} />
          <span className="nums w-6 shrink-0 text-right font-mono text-2xs text-text">{now}</span>
        </div>
      </div>
    </div>
  );
}

function MemoryDelta({ report }: { report: ExecutionReport }) {
  const b = report.memory_before.counts;
  const a = report.memory_after.counts;
  const rows: [string, number, number][] = [
    ["executions", b.executions, a.executions],
    ["capabilities", b.capabilities, a.capabilities],
    ["constraints", b.constraints, a.constraints],
  ];
  return (
    <Section title="Memory Δ · before → after">
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        {rows.map(([k, before, after]) => (
          <div key={k} className="flex items-baseline gap-2">
            <span className="label">{k}</span>
            <span className="nums font-mono text-sm text-dim">{before}</span>
            <span className="text-faint">→</span>
            <span className={`nums font-mono text-sm ${after > before ? "text-aqua" : "text-dim"}`}>{after}</span>
          </div>
        ))}
      </div>
      {report.discovered_constraints.length > 0 && (
        <div className="mt-4 border-t border-line-soft pt-4">
          <Label className="mb-2">learned this run</Label>
          <div className="flex flex-wrap gap-1.5">
            {report.discovered_constraints.map((c, i) => (
              <span
                key={i}
                className="rounded-sm border border-aqua/25 bg-aqua/[0.05] px-2 py-0.5 font-mono text-2xs text-aqua"
              >
                {c}
              </span>
            ))}
          </div>
        </div>
      )}
    </Section>
  );
}
