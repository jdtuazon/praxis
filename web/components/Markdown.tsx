import { Fragment, type ReactNode } from "react";

// A small, dependency-free Markdown renderer for the subset the agent emits when
// it writes a document: an H1 title, "## Group (n)" section headers, GFM pipe
// tables, bullet lists, and paragraphs with **bold** / `code`. Rendered to match
// the console's design language instead of dumping raw monospace — real tables,
// section headers with a priority-coloured marker, and priority pills.
//
// All content is rendered as React text children, so it is escaped by default.

const PRIORITY_TONE: Record<string, string> = {
  urgent: "border-bad/40 bg-bad/10 text-bad",
  high: "border-warn/40 bg-warn/10 text-warn",
  medium: "border-iris/40 bg-iris/10 text-iris",
  low: "border-line bg-surface-2 text-dim",
  "no priority": "border-line bg-surface-2 text-faint",
  none: "border-line bg-surface-2 text-faint",
};

const DOT_TONE: Record<string, string> = {
  urgent: "bg-bad",
  high: "bg-warn",
  medium: "bg-iris",
  low: "bg-faint",
  "no priority": "bg-faint",
  none: "bg-faint",
};

function inline(text: string, k: string): ReactNode {
  const parts: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) {
      parts.push(
        <strong key={`${k}-b${i}`} className="font-semibold text-text">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else {
      parts.push(
        <code key={`${k}-c${i}`} className="rounded-sm bg-surface-2 px-1 py-0.5 font-mono text-[0.95em] text-iris">
          {tok.slice(1, -1)}
        </code>,
      );
    }
    last = m.index + tok.length;
    i++;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts.length ? parts : text;
}

function splitRow(row: string): string[] {
  return row
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

const isSeparator = (row: string) => /^\|?[\s:|-]+\|?$/.test(row) && row.includes("-");

function Table({ rows, k }: { rows: string[]; k: string }) {
  const header = splitRow(rows[0]);
  const bodyRows = rows.slice(isSeparator(rows[1] ?? "") ? 2 : 1).map(splitRow);
  const priorityCol = header.findIndex((h) => /priorit/i.test(h));

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-line-soft">
            {header.map((h, ci) => (
              <th
                key={ci}
                className="pb-2 pr-5 font-mono text-2xs font-normal uppercase tracking-label text-faint"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line-soft">
          {bodyRows.map((cells, ri) => (
            <tr key={ri} className="align-top">
              {cells.map((c, ci) => {
                if (ci === priorityCol) {
                  const tone = PRIORITY_TONE[c.toLowerCase()] ?? "border-line bg-surface-2 text-dim";
                  return (
                    <td key={ci} className="py-2 pr-5">
                      <span className={`inline-block rounded-full border px-2 py-0.5 font-mono text-2xs ${tone}`}>
                        {c}
                      </span>
                    </td>
                  );
                }
                return (
                  <td
                    key={ci}
                    className={
                      ci === 0
                        ? "py-2 pr-5 font-mono text-2xs text-iris"
                        : "py-2 pr-5 text-sm text-dim"
                    }
                  >
                    {inline(c, `${k}-${ri}-${ci}`)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const text = h[2].trim();
      if (level === 1) {
        blocks.push(
          <h3 key={k++} className="text-base font-semibold tracking-tight text-text">
            {text}
          </h3>,
        );
      } else {
        // "## High (1)" → name + count, with a priority-coloured marker
        const cm = /^(.*?)\s*\((\d+)\)\s*$/.exec(text);
        const name = cm ? cm[1].trim() : text;
        const count = cm ? cm[2] : null;
        const dot = DOT_TONE[name.toLowerCase()] ?? "bg-iris/70";
        blocks.push(
          <div key={k++} className="flex items-center gap-2 pt-1">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden />
            <span className="text-sm font-semibold text-text">{name}</span>
            {count !== null && (
              <span className="rounded-full border border-line-soft px-1.5 py-0.5 font-mono text-2xs text-faint">
                {count}
              </span>
            )}
          </div>,
        );
      }
      i++;
      continue;
    }

    if (line.trim().startsWith("|")) {
      const tbl: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tbl.push(lines[i]);
        i++;
      }
      blocks.push(<Table key={k} rows={tbl} k={`t${k++}`} />);
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={k++} className="flex flex-col gap-1.5">
          {items.map((it, j) => (
            <li key={j} className="flex gap-2 text-sm text-dim">
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-faint" aria-hidden />
              <span>{inline(it, `l${k}-${j}`)}</span>
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s/.test(lines[i]) &&
      !lines[i].trim().startsWith("|") &&
      !/^\s*[-*]\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={k++} className="text-sm leading-relaxed text-dim">
        {para.map((p, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {inline(p, `p${k}-${j}`)}
          </Fragment>
        ))}
      </p>,
    );
  }

  return <div className="flex flex-col gap-3">{blocks}</div>;
}
