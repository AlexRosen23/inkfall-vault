"use client";

import { markPhrases } from "./Bits";
import type { Clause, ComparePair, CompareResult } from "@/lib/types";

function ClauseBox({ clause, side, phrases }: { clause: Clause | null; side: "a" | "b"; phrases: string[] }) {
  if (!clause) {
    return <div className={`diff-clause diff-empty diff-${side}`}>{side === "a" ? "(not in older version)" : "(removed in newer version)"}</div>;
  }
  return (
    <div className={`diff-clause diff-${side}`}>
      <div className="diff-heading">
        {clause.heading} <span className="mono small muted">[{clause.char_start}, {clause.char_end})</span>
      </div>
      <p className="diff-text">
        {phrases.length ? markPhrases(clause.text, phrases, side === "a" ? "w-del" : "w-ins", side === "a" ? "del" : "ins") : clause.text}
      </p>
    </div>
  );
}

function PairView({ pair, op }: { pair: ComparePair; op: string }) {
  const changes = pair.word_changes ?? [];
  const values = Object.entries(pair.value_changes ?? {});
  return (
    <div className={`diff-pair diff-op-${op}`}>
      <div className="diff-cols">
        <ClauseBox clause={pair.left} side="a" phrases={changes.map((w) => w.a)} />
        <ClauseBox clause={pair.right} side="b" phrases={changes.map((w) => w.b)} />
      </div>
      {values.length > 0 && (
        <ul className="value-changes" aria-label="Typed value changes">
          {values.map(([kind, v]) => (
            <li key={kind}>
              <span className="pill pill-brass">{kind}</span>{" "}
              <del className="w-del">{v.from.join(", ") || "none"}</del> <span aria-hidden="true">→</span>
              <span className="sr-only">changed to</span> <ins className="w-ins">{v.to.join(", ") || "none"}</ins>
            </li>
          ))}
        </ul>
      )}
      {changes.length > 0 && (
        <details className="word-changes">
          <summary>{changes.length} word-level change{changes.length === 1 ? "" : "s"}</summary>
          <ul>
            {changes.map((w, i) => (
              <li key={i}>
                <span className="mono small">{w.op}</span>{" "}
                {w.a && <del className="w-del">{w.a}</del>} {w.a && w.b && <span aria-hidden="true">→</span>}{" "}
                {w.b && <ins className="w-ins">{w.b}</ins>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function CompareView({ result }: { result: CompareResult }) {
  const changed = result.ops.filter((o) => o.op !== "equal").length;
  return (
    <div className="compare">
      <div className="compare-head">
        <div>
          <span className="mono">{result.a.ref}</span> <span className="muted">effective {result.a.effective_date}</span>
        </div>
        <span aria-hidden="true">⟶</span>
        <div>
          <span className="mono">{result.b.ref}</span> <span className="muted">effective {result.b.effective_date}</span>
        </div>
      </div>
      <p className="small muted">
        {changed} changed block{changed === 1 ? "" : "s"} · method: {result.method}
      </p>
      {result.ops.map((op, i) =>
        op.op === "equal" ? (
          <div key={i} className="diff-equal">
            {op.count} unchanged clause{op.count === 1 ? "" : "s"}
          </div>
        ) : (
          <div key={i} className="diff-block">
            <div className="diff-label">{op.op}</div>
            {op.pairs.map((p, j) => (
              <PairView key={j} pair={p} op={op.op} />
            ))}
          </div>
        ),
      )}
    </div>
  );
}
