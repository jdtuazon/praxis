import { ReactNode } from "react";

type Tone = "ok" | "warn" | "bad" | "iris" | "aqua" | "dim";

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  iris: "text-iris",
  aqua: "text-aqua",
  dim: "text-dim",
};
const TONE_PILL: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border-ok/30",
  warn: "bg-warn/10 text-warn border-warn/30",
  bad: "bg-bad/10 text-bad border-bad/30",
  iris: "bg-iris/10 text-iris border-iris/30",
  aqua: "bg-aqua/10 text-aqua border-aqua/30",
  dim: "bg-white/5 text-dim border-line",
};

export const STATUS_TONE: Record<string, Tone> = {
  success: "ok",
  partial: "warn",
  failed: "bad",
  rolled_back: "iris",
  skipped: "dim",
  pending: "dim",
  running: "aqua",
};

export function Pill({ tone = "dim", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 font-mono text-2xs uppercase tracking-label ${TONE_PILL[tone]}`}
    >
      {children}
    </span>
  );
}

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`label ${className}`}>{children}</div>;
}

export function Section({
  title,
  aside,
  children,
  className = "",
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel animate-fade-up p-5 ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <Label>{title}</Label>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Tile({
  value,
  unit,
  label,
  tone = "dim",
  emphasize = false,
}: {
  value: ReactNode;
  unit?: string;
  label: string;
  tone?: Tone;
  emphasize?: boolean;
}) {
  return (
    <div
      className={`rounded-sm border px-4 py-3 ${
        emphasize ? "border-iris/30 bg-iris/[0.04]" : "border-line-soft bg-surface-2"
      }`}
    >
      <div className={`nums font-mono text-2xl font-medium leading-none ${TONE_TEXT[tone]}`}>
        {value}
        {unit ? <span className="ml-1 text-sm text-faint">{unit}</span> : null}
      </div>
      <div className="label mt-2">{label}</div>
    </div>
  );
}

export function Delta({ value, suffix = "" }: { value: number; suffix?: string }) {
  if (!value) return <span className="text-faint">—</span>;
  const positive = value > 0;
  return (
    <span className={`nums font-mono ${positive ? "text-aqua" : "text-bad"}`}>
      {positive ? "−" : "+"}
      {Math.abs(value)}
      {suffix}
    </span>
  );
}

export function Spinner() {
  return (
    <span
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-iris/30 border-t-iris"
      aria-hidden
    />
  );
}

/** A compact comparison bar: value rendered against a max, with an emphasized fill. */
export function Bar({
  value,
  max,
  tone = "iris",
}: {
  value: number;
  max: number;
  tone?: Tone;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  const fill = tone === "bad" ? "bg-bad" : tone === "aqua" ? "bg-aqua" : "bg-iris";
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.04]">
      <div className={`h-full rounded-full ${fill}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
