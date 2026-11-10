"use client";

import { Fragment, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api, errorText, when } from "@/lib/api";
import type { AnswerSentence, Citation, CompareResult, DocumentPayload } from "@/lib/types";
import { CitationChip, KV, SupportBadge } from "./Bits";
import { CompareView } from "./CompareView";
import { Modal } from "./Modal";

export interface InspectTarget {
  versionId: number;
  span?: { start: number; end: number };
  /** The answer sentence being verified (left pane of the side-by-side view). */
  sentence?: AnswerSentence;
  citation?: Citation;
  /** Free-form context shown on the left when there is no answer sentence (e.g. a conflict quote). */
  context?: string;
  initialTab?: "document" | "compare";
}

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The stored text, character for character. Markdown heading lines are styled and their "#" markers dimmed, but
 *  every character stays in place so a citation's offsets always point at exactly what is on screen. */
function PaperText({ text, span, pulse }: { text: string; span?: { start: number; end: number }; pulse: number }) {
  const markRef = useRef<HTMLElement>(null);
  const valid = !!span && span.start >= 0 && span.end <= text.length && span.start < span.end;

  useEffect(() => {
    if (!valid) return;
    markRef.current?.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
  }, [valid, span?.start, span?.end, pulse]);

  const s = valid ? span : undefined;
  let first = true;
  const out: ReactNode[] = [];
  let pos = 0;
  const lines = text.split("\n");
  lines.forEach((line, i) => {
    const start = pos;
    const end = pos + line.length;
    const marker = /^#{1,6} /.exec(line)?.[0].length ?? 0;
    const cuts = new Set([start, end, start + marker]);
    if (s) {
      if (s.start > start && s.start < end) cuts.add(s.start);
      if (s.end > start && s.end < end) cuts.add(s.end);
    }
    const pts = [...cuts].sort((a, b) => a - b);
    const kids: ReactNode[] = [];
    for (let k = 0; k < pts.length - 1; k++) {
      const a = pts[k]!;
      const b = pts[k + 1]!;
      if (a === b) continue;
      let node: ReactNode = text.slice(a, b);
      if (marker && a < start + marker) node = <span className="md-mark">{node}</span>;
      if (s && a >= s.start && b <= s.end) {
        node = (
          <mark
            ref={first ? markRef : undefined}
            className="cite-mark"
            aria-label={first ? `Highlighted span, characters ${s.start} to ${s.end}` : undefined}
          >
            {node}
          </mark>
        );
        first = false;
      }
      kids.push(<Fragment key={`${a}-${pulse}`}>{node}</Fragment>);
    }
    out.push(
      <span key={start} className={marker ? `paper-h paper-h${Math.min(marker - 1, 3)}` : undefined}>
        {kids}
      </span>,
    );
    if (i < lines.length - 1) out.push(s && end >= s.start && end < s.end ? <mark key={`n${end}`} className="cite-mark">{"\n"}</mark> : "\n");
    pos = end + 1;
  });
  return <div className="paper-text">{out}</div>;
}

function AccessDrawer({ doc, onClose, onOpenVersion }: { doc: DocumentPayload; onClose: () => void; onOpenVersion: (vid: number) => void }) {
  const hid = useId();
  return (
    <aside className="drawer" aria-labelledby={hid}>
      <div className="drawer-head">
        <h3 id={hid}>Access &amp; lineage</h3>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close access and lineage drawer">
          Close <kbd>Esc</kbd>
        </button>
      </div>
      <h4>Why you can read this</h4>
      <p>
        <span className="pill pill-ok">{doc.access.decision}</span>
        {doc.access.ethical_wall_applies && <span className="pill pill-warn">ethical wall applies</span>}
      </p>
      <ul className="reasons">
        {doc.access.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <KV items={[["ACL groups", <span key="g" className="mono">{doc.access.acl_groups.join(", ") || "—"}</span>]]} />
      <h4>Lineage</h4>
      <KV
        items={[
          ["Checksum (SHA-256)", <code key="c" className="break">{doc.lineage.checksum_sha256}</code>],
          ["Ingested at", when(doc.lineage.ingested_at)],
          ["Ingested by", <span key="b" className="mono">{doc.lineage.ingested_by}</span>],
          ["Extraction", doc.lineage.extraction_method],
          ["Source file", <code key="f" className="break">{doc.lineage.source_filename}</code>],
          ["MIME / size", `${doc.lineage.source_mime} · ${doc.lineage.byte_size.toLocaleString()} bytes`],
          ["Retention", doc.lineage.retention],
          [
            "Status",
            doc.lineage.in_force_today ? (
              <span key="s" className="pill pill-ok">in force</span>
            ) : (
              <span key="s" className="pill pill-warn">
                superseded{doc.lineage.superseded_by_version ? ` by v${doc.lineage.superseded_by_version}` : ""}
              </span>
            ),
          ],
        ]}
      />
      <h4>Versions you may read</h4>
      <ul className="version-list">
        {doc.versions.map((v) => (
          <li key={v.version_id}>
            {v.version_id === doc.version_id ? (
              <span className="current">
                v{v.version} · {v.effective_date} <span className="muted">(open)</span>
              </span>
            ) : (
              <button type="button" className="link-btn" onClick={() => onOpenVersion(v.version_id)}>
                v{v.version} · {v.effective_date}
              </button>
            )}
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function DocumentInspector({
  target,
  onClose,
  onCompared,
  onVerified,
}: {
  target: InspectTarget;
  onClose: () => void;
  onCompared?: () => void;
  onVerified?: () => void;
}) {
  const titleId = useId();
  const [vid, setVid] = useState(target.versionId);
  const [state, setState] = useState<{ vid: number; doc?: DocumentPayload; error?: string } | null>(null);
  const [tab, setTab] = useState<"document" | "compare">(target.initialTab ?? "document");
  const [drawer, setDrawer] = useState(false);
  const [localSpan, setLocalSpan] = useState<{ start: number; end: number } | null>(null);
  const [pulse, setPulse] = useState(0);
  const [cmpA, setCmpA] = useState<number | null>(null);
  const [cmpB, setCmpB] = useState<number | null>(null);
  const [cmp, setCmp] = useState<{ result?: CompareResult; error?: string; busy?: boolean }>({});
  const [activeCitation, setActiveCitation] = useState<Citation | undefined>(target.citation);

  useEffect(() => {
    let cancelled = false;
    api<DocumentPayload>(`/api/documents/${vid}`)
      .then((doc) => {
        if (cancelled) return;
        setState({ vid, doc });
        if (vid === target.versionId) onVerified?.();
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ vid, error: errorText(e) });
      });
    return () => {
      cancelled = true;
    };
    // onVerified is a notification only; re-running on its identity would refetch needlessly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vid, target.versionId]);

  const loading = !state || state.vid !== vid;
  const doc = !loading ? state?.doc : undefined;
  const error = !loading ? state?.error : undefined;

  const citationSpan =
    activeCitation && activeCitation.version_id === vid ? { start: activeCitation.char_start, end: activeCitation.char_end } : undefined;
  const targetSpan = vid === target.versionId ? target.span : undefined;
  const span = localSpan ?? citationSpan ?? targetSpan;

  const openVersion = (v: number) => {
    setLocalSpan(null);
    setVid(v);
    setTab("document");
  };

  const versions = doc?.versions ?? [];
  const defaultA = versions.length >= 2 ? versions[versions.length - 2]!.version_id : null;
  const defaultB = versions.length >= 2 ? versions[versions.length - 1]!.version_id : null;
  const a = cmpA ?? defaultA;
  const b = cmpB ?? defaultB;

  const runCompare = async () => {
    if (a == null || b == null || a === b) return;
    setCmp({ busy: true });
    try {
      const result = await api<CompareResult>(`/api/compare/${a}/${b}`);
      setCmp({ result });
      onCompared?.();
    } catch (e) {
      setCmp({ error: errorText(e) });
    }
  };

  const quoteMatches = activeCitation && doc && activeCitation.version_id === vid
    ? doc.text.slice(activeCitation.char_start, activeCitation.char_end) === activeCitation.quote
    : null;

  return (
    <Modal
      labelledBy={titleId}
      onEscape={() => (drawer ? setDrawer(false) : onClose())}
      className="inspector"
    >
      <div className="inspector-head">
        <div className="inspector-title">
          <div className="kicker">{target.sentence ? "Side-by-side verification" : "Document viewer"}</div>
          <h2 id={titleId}>
            {doc ? (
              <>
                <span className="mono ref">{doc.ref}</span> {doc.title}
              </>
            ) : (
              `Version ${vid}`
            )}
          </h2>
        </div>
        <div className="inspector-actions">
          {doc && (
            <button type="button" className="btn btn-ghost" aria-expanded={drawer} onClick={() => setDrawer((d) => !d)}>
              Access &amp; lineage
            </button>
          )}
          <button type="button" className="btn" onClick={onClose} data-autofocus>
            Close <kbd>Esc</kbd>
          </button>
        </div>
      </div>

      <div className={`inspector-body${drawer ? " with-drawer" : ""}`}>
        <div className="claim-pane">
          {target.sentence ? (
            <>
              <h3 className="pane-title">Answer sentence</h3>
              <blockquote className="claim">{target.sentence.text}</blockquote>
              <p>
                Support: <SupportBadge support={target.sentence.support} />
              </p>
              {target.sentence.notes.length > 0 && (
                <ul className="notes">
                  {target.sentence.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              <h3 className="pane-title">Citations</h3>
              <div className="chip-row">
                {target.sentence.citations.map((c) => (
                  <CitationChip
                    key={`${c.pid}-${c.char_start}`}
                    c={c}
                    active={activeCitation?.pid === c.pid && activeCitation.char_start === c.char_start}
                    onOpen={(cc) => {
                      setActiveCitation(cc);
                      setLocalSpan(null);
                      setPulse((p) => p + 1);
                      if (cc.version_id !== vid) openVersion(cc.version_id);
                    }}
                  />
                ))}
              </div>
            </>
          ) : target.context ? (
            <>
              <h3 className="pane-title">Context</h3>
              <blockquote className="claim">{target.context}</blockquote>
            </>
          ) : null}

          {activeCitation && (
            <div className="cite-detail">
              <KV
                items={[
                  ["Passage", activeCitation.pid],
                  ["Source", <span key="r" className="mono">{activeCitation.ref}</span>],
                  ["Span", <span key="s" className="mono">[{activeCitation.char_start}, {activeCitation.char_end})</span>],
                ]}
              />
              {quoteMatches === true && <p className="ok small">✓ Cited quote matches the stored text at this span.</p>}
              {quoteMatches === false && <p className="warn small">⚠ Cited quote does not match the stored text at this span.</p>}
            </div>
          )}

          {doc && (
            <>
              <h3 className="pane-title">Document</h3>
              <KV
                items={[
                  ["Effective", doc.effective_date],
                  ["Type", doc.doc_type],
                  ["Collection", doc.collection],
                  ["Classification", doc.classification],
                  ...(doc.matter ? ([["Matter", doc.matter]] as [string, string][]) : []),
                  ...(doc.amends ? ([["Amends", <span key="a" className="mono">{doc.amends}</span>]] as [string, ReactNode][]) : []),
                  ["Parties", (doc.parties ?? []).join("; ") || "—"],
                  ["Tags", (doc.tags ?? []).join(", ") || "—"],
                ]}
              />
              <h3 className="pane-title">Clauses</h3>
              <ol className="outline">
                {doc.chunks.map((c) => (
                  <li key={c.chunk_id}>
                    <button
                      type="button"
                      className={`link-btn${span && span.start <= c.char_start && c.char_end <= span.end + 1 ? " current" : ""}`}
                      onClick={() => {
                        setLocalSpan({ start: c.char_start, end: c.char_end });
                        setPulse((p) => p + 1);
                        setTab("document");
                      }}
                    >
                      {c.heading || `chunk ${c.chunk_id}`} <span className="mono small muted">[{c.char_start}, {c.char_end})</span>
                    </button>
                  </li>
                ))}
              </ol>
            </>
          )}
        </div>

        <div className="paper-pane">
          {doc && (
            <div className="tabs" role="tablist" aria-label="Document views">
              <button type="button" role="tab" aria-selected={tab === "document"} onClick={() => setTab("document")}>
                Document text
              </button>
              <button type="button" role="tab" aria-selected={tab === "compare"} onClick={() => setTab("compare")}>
                Compare versions ({versions.length})
              </button>
            </div>
          )}
          {loading && <p className="muted" aria-live="polite">Loading version {vid}…</p>}
          {error && (
            <div className="banner banner-error" role="alert">
              {error}
            </div>
          )}
          {doc && tab === "document" && (
            <article className="paper" aria-label={`Full text of ${doc.ref}`}>
              {!doc.lineage.in_force_today && (
                <div className="paper-flag">Historical version — superseded{doc.lineage.superseded_by_version ? ` by v${doc.lineage.superseded_by_version}` : ""}</div>
              )}
              <PaperText text={doc.text} span={span} pulse={pulse} />
            </article>
          )}
          {doc && tab === "compare" && versions.length < 2 && (
            <p className="muted">Only one version of this document is authorized for you, so there is nothing to compare.</p>
          )}
          {doc && tab === "compare" && versions.length >= 2 && (
            <div className="compare-pane">
              <div className="compare-controls">
                <label>
                  Older
                  <select value={a ?? ""} onChange={(e) => setCmpA(Number(e.target.value))}>
                    {versions.map((v) => (
                      <option key={v.version_id} value={v.version_id}>
                        v{v.version} · {v.effective_date}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Newer
                  <select value={b ?? ""} onChange={(e) => setCmpB(Number(e.target.value))}>
                    {versions.map((v) => (
                      <option key={v.version_id} value={v.version_id}>
                        v{v.version} · {v.effective_date}
                      </option>
                    ))}
                  </select>
                </label>
                <button type="button" className="btn btn-brass" onClick={runCompare} disabled={a == null || b == null || a === b || cmp.busy}>
                  {cmp.busy ? "Comparing…" : "Compare"}
                </button>
              </div>
              {a === b && <p className="small muted">Pick two different versions.</p>}
              {cmp.error && <div className="banner banner-error" role="alert">{cmp.error}</div>}
              {cmp.result && <CompareView result={cmp.result} />}
            </div>
          )}
        </div>

        {drawer && doc && <AccessDrawer doc={doc} onClose={() => setDrawer(false)} onOpenVersion={openVersion} />}
      </div>
    </Modal>
  );
}
