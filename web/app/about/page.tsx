import { PageHeader } from "@/components/PageHeader";
import { Label } from "@/components/ui";

const CHEAP_VS_REAL: [string, string, string][] = [
  ["Memory", "a vector store of past prompts", "structured knowledge — constraints, capabilities, plan shapes — read before acting to change decisions"],
  ["Synthesis", "a lookup table of API endpoints", "reason → typed contract → schema-validate → test → register (probationary → trusted)"],
  ["Learning", "“we added more examples”", "a measurable behaviour change, proven with a negative control"],
];

const PIPELINE = [
  ["Plan", "decompose the instruction; reuse a learned plan shape or rewrite it from learned rules"],
  ["Synthesize", "fill any capability gap at runtime — build it, validate against the live schema, test it"],
  ["Execute", "run the steps; cached ids skip probes, enum facts pre-validate, permissions switch tooling"],
  ["Validate", "score confidence; on a failed step after side effects, compensate (reversible) or flag (irreversible)"],
  ["Learn", "extract constraints, update stats, promote capabilities — so the next run differs"],
];

export default function AboutPage() {
  return (
    <>
      <PageHeader title="An agent that learns by doing.">
        Praxis turns a natural-language instruction into Linear actions, invents the capabilities it’s
        missing, and gets measurably better with use: not by retraining, but by extracting structured
        knowledge from every execution and using it to decide differently next time.
      </PageHeader>

      <section className="panel mb-5 p-6">
        <Label className="mb-4">the distinction it’s built around</Label>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="label border-b border-line-soft [&>th]:pb-2 [&>th]:pr-6 [&>th]:font-normal">
                <th></th>
                <th>the cheap version</th>
                <th>what Praxis does</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {CHEAP_VS_REAL.map(([k, cheap, real]) => (
                <tr key={k} className="align-top [&>td]:py-3 [&>td]:pr-6">
                  <td className="font-medium text-text">{k}</td>
                  <td className="text-faint">{cheap}</td>
                  <td className="text-dim">{real}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel mb-5 p-6">
        <Label className="mb-4">the loop · a LangGraph state machine</Label>
        <ol className="flex flex-col gap-3">
          {PIPELINE.map(([stage, desc], i) => (
            <li key={stage} className="flex gap-4">
              <span className="nums mt-0.5 font-mono text-2xs text-iris">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <div className="text-sm font-medium text-text">{stage}</div>
                <div className="mt-0.5 text-2xs leading-relaxed text-faint">{desc}</div>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <div className="grid gap-5 sm:grid-cols-2">
        <section className="panel p-6">
          <Label className="mb-3">two memory layers</Label>
          <p className="text-sm leading-relaxed text-dim">
            <span className="text-text">Execution memory</span> stores instructions, outcomes, cost, and
            the best plan shape per intent-signature.{" "}
            <span className="text-text">Capability memory</span> stores executable skills (with a
            lifecycle), per-pattern stats, and the learned world-model: cached ids, enum facts,
            permission boundaries, and plan-rewriting workflow rules.
          </p>
        </section>
        <section className="panel p-6">
          <Label className="mb-3">stack</Label>
          <p className="text-sm leading-relaxed text-dim">
            Python · LangGraph orchestration · pluggable Anthropic / OpenAI reasoning · Linear GraphQL ·
            SQLite memory · a deterministic offline simulation for testing. This console is Next.js +
            Tailwind over the same structured report the CLI renders.
          </p>
          <a
            className="link mt-3 inline-block text-sm"
            href="https://github.com/jdtuazon/watermelon"
            target="_blank"
            rel="noreferrer"
          >
            ↗ read the source & ARCHITECTURE.md
          </a>
        </section>
      </div>
    </>
  );
}
