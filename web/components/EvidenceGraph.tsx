"use client";

import { useMemo, useState, type KeyboardEvent } from "react";
import type { AskResult, GraphEdge, GraphNode, Passage } from "@/lib/types";

const COLS = { question: 60, clause: 290, document: 540, entity: 790 } as const;
const W = { question: 90, clause: 190, document: 200, entity: 160 } as const;
const ROW = 46;
const TOP = 40;
const NODE_H = 30;

const EDGE_TEXT: Record<GraphEdge["kind"], string> = {
  retrieved: "retrieved for the question",
  part_of: "clause is part of document",
  party: "document names party",
  amends: "amends",
  supersedes: "supersedes",
  contradicts: "contradicts",
};

function clip(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

interface Placed extends GraphNode {
  x: number;
  y: number;
  w: number;
}

export function EvidenceGraph({
  graph,
  sources,
  onOpenDocument,
  onOpenPassage,
}: {
  graph: AskResult["graph"];
  sources: Passage[];
  onOpenDocument: (versionId: number) => void;
  onOpenPassage: (p: Passage) => void;
}) {
  const [active, setActive] = useState<string | null>(null);

  const { placed, byId, height } = useMemo(() => {
    const rank = new Map<string, number>();
    for (const e of graph.edges) if (e.kind === "retrieved" && e.rank != null) rank.set(e.to, e.rank);
    const cols: Record<GraphNode["kind"], GraphNode[]> = { question: [], clause: [], document: [], entity: [] };
    for (const n of graph.nodes) cols[n.kind]?.push(n);
    cols.clause.sort((a, b) => (rank.get(a.id) ?? 99) - (rank.get(b.id) ?? 99));
    cols.entity.sort((a, b) => a.label.localeCompare(b.label));
    const maxRows = Math.max(1, ...Object.values(cols).map((c) => c.length));
    const h = TOP + maxRows * ROW + 10;
    const out: Placed[] = [];
    (Object.keys(cols) as GraphNode["kind"][]).forEach((kind) => {
      const list = cols[kind];
      const offset = TOP + ((maxRows - list.length) * ROW) / 2;
      list.forEach((n, i) => out.push({ ...n, x: COLS[kind], y: offset + i * ROW + ROW / 2, w: W[kind] }));
    });
    return { placed: out, byId: new Map(out.map((n) => [n.id, n])), height: h };
  }, [graph]);

  const pidMap = useMemo(() => new Map(sources.map((p) => [p.pid, p])), [sources]);

  const connected = useMemo(() => {
    if (!active) return null;
    const set = new Set<string>([active]);
    for (const e of graph.edges) {
      if (e.from === active) set.add(e.to);
      if (e.to === active) set.add(e.from);
    }
    return set;
  }, [active, graph.edges]);

  const activate = (n: Placed) => {
    if (n.kind === "document" && n.version_id != null) onOpenDocument(n.version_id);
    if (n.kind === "clause" && n.pid) {
      const p = pidMap.get(n.pid);
      if (p) onOpenPassage(p);
    }
  };

  const onKey = (e: KeyboardEvent<SVGGElement>, n: Placed) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      activate(n);
    }
  };

  const edgePath = (e: GraphEdge): string | null => {
    const a = byId.get(e.from);
    const b = byId.get(e.to);
    if (!a || !b) return null;
    if (a.kind === b.kind) {
      // same column: arc outside the column (left for clauses, right for documents)
      const side = a.kind === "clause" ? -1 : 1;
      const x = a.x + (side > 0 ? a.w : 0);
      const bulge = 46 + Math.abs(a.y - b.y) * 0.15;
      return `M ${x} ${a.y} C ${x + side * bulge} ${a.y}, ${x + side * bulge} ${b.y}, ${x} ${b.y}`;
    }
    const x1 = a.x + a.w;
    const x2 = b.x;
    const mx = (x1 + x2) / 2;
    return `M ${x1} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${x2} ${b.y}`;
  };

  const activeNode = active ? byId.get(active) : undefined;
  const activeEdges = active ? graph.edges.filter((e) => e.from === active || e.to === active) : [];
  const passage = activeNode?.kind === "clause" && activeNode.pid ? pidMap.get(activeNode.pid) : undefined;

  return (
    <div className="graph-wrap">
      <p className="small muted">
        Built only from indexed metadata and retrieval links (retrieval ranks, clause membership, named parties, amendment and
        version links, detected value conflicts). It is not inferred by a model and does not assert facts beyond those links.
      </p>
      <div className="graph-legend" aria-label="Legend">
        <span><i className="lg lg-question" /> question</span>
        <span><i className="lg lg-clause" /> clause</span>
        <span><i className="lg lg-cited" /> cited clause</span>
        <span><i className="lg lg-inject" /> instruction-like text</span>
        <span><i className="lg lg-document" /> document</span>
        <span><i className="lg lg-historical" /> historical version</span>
        <span><i className="lg lg-entity" /> entity</span>
        <span><i className="le le-retrieved" /> retrieved</span>
        <span><i className="le le-part_of" /> part of</span>
        <span><i className="le le-party" /> party</span>
        <span><i className="le le-amends" /> amends</span>
        <span><i className="le le-supersedes" /> supersedes</span>
        <span><i className="le le-contradicts" /> contradicts</span>
      </div>
      <div className="graph-scroll">
        <svg
          className="graph"
          viewBox={`0 0 ${COLS.entity + W.entity + 20} ${height}`}
          role="group"
          aria-label="Evidence graph: question, retrieved clauses, documents and entities"
        >
          {(["question", "clause", "document", "entity"] as const).map((k) => (
            <text key={k} x={COLS[k]} y={18} className="graph-col">
              {k === "question" ? "QUESTION" : k === "clause" ? "CLAUSES (by rank)" : k === "document" ? "DOCUMENTS" : "ENTITIES"}
            </text>
          ))}
          <g aria-hidden="true">
            {graph.edges.map((e, i) => {
              const d = edgePath(e);
              if (!d) return null;
              const dim = connected && !(connected.has(e.from) && connected.has(e.to) && (e.from === active || e.to === active));
              const width = e.kind === "retrieved" && e.rank ? Math.max(1, 3.5 - e.rank * 0.35) : undefined;
              return <path key={i} d={d} className={`edge edge-${e.kind}${dim ? " dim" : ""}`} style={width ? { strokeWidth: width } : undefined} />;
            })}
          </g>
          {placed.map((n) => {
            const dim = connected && !connected.has(n.id);
            const clickable = n.kind === "document" || (n.kind === "clause" && !!n.pid);
            const cls = [
              "node",
              `node-${n.kind}`,
              n.cited ? "node-cited" : "",
              n.injection ? "node-inject" : "",
              n.kind === "document" && n.in_force === false ? "node-historical" : "",
              dim ? "dim" : "",
              active === n.id ? "node-active" : "",
            ].join(" ");
            const label =
              n.kind === "clause"
                ? `${n.pid ?? ""} ${n.label}`
                : n.kind === "document"
                  ? n.label
                  : n.label;
            const aria =
              n.kind === "document"
                ? `Document ${n.label}${n.title ? `, ${n.title}` : ""}${n.in_force === false ? ", historical" : ""}. Press Enter to open.`
                : n.kind === "clause"
                  ? `Clause ${n.pid ?? ""} ${n.label}${n.cited ? ", cited" : ""}${n.injection ? ", contains instruction-like text" : ""}. Press Enter to open.`
                  : n.kind === "entity"
                    ? `Entity ${n.label}`
                    : "The question";
            return (
              <g
                key={n.id}
                className={cls}
                tabIndex={0}
                role={clickable ? "button" : "img"}
                aria-label={aria}
                onMouseEnter={() => setActive(n.id)}
                onMouseLeave={() => setActive((a) => (a === n.id ? null : a))}
                onFocus={() => setActive(n.id)}
                onBlur={() => setActive((a) => (a === n.id ? null : a))}
                onClick={() => activate(n)}
                onKeyDown={(e) => onKey(e, n)}
              >
                <title>{n.title ? `${n.label} — ${n.title}` : n.label}</title>
                {n.kind === "question" ? (
                  <circle cx={n.x + 20} cy={n.y} r={16} />
                ) : (
                  <rect x={n.x} y={n.y - NODE_H / 2} width={n.w} height={NODE_H} rx={n.kind === "entity" ? 15 : 4} />
                )}
                <text x={n.kind === "question" ? n.x + 42 : n.x + 8} y={n.y + 4}>
                  {clip(n.kind === "question" ? "Q" : label, n.kind === "document" ? 27 : n.kind === "clause" ? 26 : 22)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <div className="graph-detail" aria-live="polite">
        {!activeNode && <span className="muted small">Hover or focus a node for details. Enter opens clauses and documents.</span>}
        {activeNode && (
          <div>
            <strong className="mono">{activeNode.kind}</strong> · {activeNode.label}
            {activeNode.title && <div>{activeNode.title}</div>}
            {activeNode.kind === "document" && (
              <div className="small muted">
                {activeNode.doc_type} · effective {activeNode.effective_date} · {activeNode.in_force ? "in force" : "historical"}
              </div>
            )}
            {passage && (
              <div className="small">
                <span className="mono">{passage.ref}</span> · rank {passage.rank} ·{" "}
                {Object.entries(passage.method_ranks)
                  .map(([m, r]) => `${m} #${r}`)
                  .join(", ")}
                {passage.injection_flags.length > 0 && <span className="warn"> · instruction-like text: {passage.injection_flags.join(", ")}</span>}
              </div>
            )}
            {activeEdges.length > 0 && (
              <ul className="small edge-list">
                {activeEdges.map((e, i) => {
                  const other = byId.get(e.from === active ? e.to : e.from);
                  return (
                    <li key={i}>
                      {e.from === active ? "→" : "←"} {EDGE_TEXT[e.kind]}
                      {e.rank ? ` (rank ${e.rank})` : ""}
                      {e.label ? ` (${e.label})` : ""}: <span className="mono">{other?.label ?? "?"}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
