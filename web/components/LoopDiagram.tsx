"use client";

import { useEffect, useState } from "react";

// High-level shape of the loop — names only, so the diagram stays a general
// picture; the per-stage detail lives in the legend below.
const STAGES: ReadonlyArray<readonly [string, string, number]> = [
  ["01", "Plan", 104],
  ["02", "Synthesize", 292],
  ["03", "Execute", 480],
  ["04", "Validate", 668],
  ["05", "Learn", 856],
];

const LEGEND: ReadonlyArray<readonly [string, string, string]> = [
  ["01", "Plan", "decompose the instruction; reuse a learned plan shape, or rewrite it from learned rules"],
  ["02", "Synthesize", "fill any capability gap at runtime: build it, validate it against the live schema, test it"],
  ["03", "Execute", "run the steps; cached ids skip probes, enum facts pre-validate, permissions switch tooling"],
  ["04", "Validate", "score confidence; compensate a reversible failure, flag an irreversible one"],
  ["05", "Learn", "extract constraints, update stats, promote capabilities, so the next run differs"],
];

// The closed path the signal travels: across the stages, then back along the
// feedback arc. Kept in one place so the dot and the visible arc stay in sync.
const LOOP_PATH =
  "M104,100 H856 C 940,115 940,212 856,212 L104,212 C 20,212 20,115 104,100 Z";

export function LoopDiagram() {
  const [animate, setAnimate] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setAnimate(!mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return (
    <div>
      <svg
        viewBox="0 0 960 250"
        className="w-full"
        role="img"
        aria-label="Praxis runs a five-stage loop — plan, synthesize, execute, validate, learn — and feeds what it learns back into the next run."
      >
        {/* instruction enters */}
        <text x={104} y={34} textAnchor="middle" className="fill-faint font-mono text-[11px] tracking-[0.08em]">
          INSTRUCTION
        </text>
        <path d="M104,42 V73" className="stroke-line" strokeWidth={1.5} fill="none" />
        <path d="M104,77 l-4.5,-8 h9 z" className="fill-faint" />

        {/* connectors between stages */}
        <g className="stroke-line" strokeWidth={1.5} fill="none">
          <path d="M178,100 H213" />
          <path d="M366,100 H401" />
          <path d="M554,100 H589" />
          <path d="M742,100 H777" />
        </g>
        <g className="fill-faint">
          <path d="M217,100 l-7,-4.5 v9 z" />
          <path d="M405,100 l-7,-4.5 v9 z" />
          <path d="M593,100 l-7,-4.5 v9 z" />
          <path d="M781,100 l-7,-4.5 v9 z" />
        </g>

        {/* feedback arc — Learn teaches Plan */}
        <path
          d="M856,125 C 940,140 940,212 856,212 L104,212 C 20,212 20,140 104,125"
          className="fill-none stroke-iris/60 animate-march"
          strokeWidth={1.5}
          strokeDasharray="5 7"
        />
        <path d="M104,125 l-4.5,9 h9 z" className="fill-iris/70" />
        <text x={480} y={170} textAnchor="middle" className="fill-dim font-mono text-[11px] tracking-[0.08em]">
          ↺&#160;&#160;EVERY RUN TEACHES THE NEXT
        </text>

        {/* the signal travelling the loop */}
        {animate && (
          <circle r={4.5} className="fill-aqua" style={{ filter: "drop-shadow(0 0 6px rgba(79,208,200,0.85))" }}>
            <animateMotion dur="5.2s" repeatCount="indefinite" path={LOOP_PATH} />
          </circle>
        )}

        {/* stage chips */}
        {STAGES.map(([num, name, cx], i) => (
          <g key={num} className="animate-fade-up" style={{ animationDelay: `${0.05 + i * 0.12}s` }}>
            <rect x={cx - 74} y={75} width={148} height={50} rx={9} className="fill-surface-2 stroke-line" strokeWidth={1} />
            <text x={cx - 60} y={94} className="fill-iris font-mono text-[11px] tracking-[0.04em]">
              {num}
            </text>
            <text x={cx} y={107} textAnchor="middle" className="fill-text font-sans text-[16px] font-semibold">
              {name}
            </text>
          </g>
        ))}
      </svg>

      {/* legend — the detail behind each stage */}
      <div className="mt-6 grid gap-x-10 gap-y-4 border-t border-line-soft pt-6 sm:grid-cols-2">
        {LEGEND.map(([num, name, desc]) => (
          <div key={num} className="flex gap-3">
            <span className="nums mt-0.5 font-mono text-2xs text-iris">{num}</span>
            <div>
              <div className="text-sm font-medium text-text">{name}</div>
              <div className="mt-0.5 text-2xs leading-relaxed text-faint">{desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

