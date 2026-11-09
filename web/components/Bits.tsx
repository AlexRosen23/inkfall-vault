"use client";

import type { ReactNode } from "react";
import { humanize } from "@/lib/api";
import type { Citation } from "@/lib/types";

const STATUS_TEXT: Record<string, string> = {
  supported: "Supported by cited evidence",
  contradictory: "Contradictory evidence",
  insufficient_evidence: "Insufficient evidence — abstained",
  partially_unsupported: "Partially unsupported",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`status status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {STATUS_TEXT[status] ?? humanize(status)}
    </span>
  );
}

export function SupportBadge({ support }: { support: string }) {
  return <span className={`support support-${support}`}>{humanize(support)}</span>;
}

export function SummaryStatusBadge({ status }: { status: string }) {
  return <span className={`brief-status brief-${status}`}>{status}</span>;
}

/** A button-shaped citation chip, e.g. "P2 · CV-SLA-ORION@1". Native <button> gives Enter/Space for free. */
export function CitationChip({ c, onOpen, active }: { c: Citation; onOpen: (c: Citation) => void; active?: boolean }) {
  return (
    <button
      type="button"
      className={`chip${active ? " chip-active" : ""}`}
      onClick={() => onOpen(c)}
      aria-label={`Verify citation ${c.pid} in ${c.ref}, characters ${c.char_start} to ${c.char_end}`}
    >
      <span className="chip-pid">{c.pid}</span>
      <span aria-hidden="true">·</span>
      <span className="mono">{c.ref}</span>
    </button>
  );
}

export function Section({
  id,
  title,
  kicker,
  actions,
  children,
  className,
}: {
  id?: string;
  title: string;
  kicker?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const hid = id ? `${id}-h` : undefined;
  return (
    <section id={id} className={`panel ${className ?? ""}`} aria-labelledby={hid}>
      <div className="panel-head">
        <div>
          {kicker && <div className="kicker">{kicker}</div>}
          <h2 id={hid}>{title}</h2>
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} className="kv-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Wrap the first sequential occurrence of each phrase in an element; text stays plain React text. */
export function markPhrases(text: string, phrases: string[], className: string, Tag: "ins" | "del" | "mark" = "mark"): ReactNode[] {
  const out: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const p of phrases) {
    if (!p) continue;
    const i = text.indexOf(p, cursor);
    if (i < 0) continue;
    if (i > cursor) out.push(text.slice(cursor, i));
    out.push(
      <Tag key={key++} className={className}>
        {text.slice(i, i + p.length)}
      </Tag>,
    );
    cursor = i + p.length;
  }
  out.push(text.slice(cursor));
  return out;
}
