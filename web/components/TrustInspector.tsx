"use client";

import { pct } from "@/lib/api";
import type { AskResult, Citation } from "@/lib/types";
import { CitationChip } from "./Bits";

export function TrustInspector({
  result,
  onOpenCitation,
}: {
  result: AskResult;
  onOpenCitation: (c: Citation, context?: string) => void;
}) {
  const t = result.trust;
  const cov = Math.max(0, Math.min(1, t.evidence_coverage));
  const refByVid = new Map(result.sources.map((s) => [s.version_id, s.ref]));
  const injectionInQuestion = t.untrusted_instructions_in_question;
  const injectionInSources = t.untrusted_instructions_in_sources;

  return (
    <div className="trust">
      <div className="trust-block">
        <h3 id="coverage-label">Evidence coverage</h3>
        <div className="meter" role="meter" aria-labelledby="coverage-label" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(cov * 100)}>
          <div className="meter-fill" style={{ width: `${cov * 100}%` }} />
          <span className="meter-text">{pct(cov, 0)}</span>
        </div>
        <p className="small muted">
          <strong>Diagnostic, not a probability of truth.</strong> {t.note}
        </p>
        <div className="terms">
          {t.matched_terms.map((x) => (
            <span key={`m-${x}`} className="term term-hit" title="found in top authorized passages">✓ {x}</span>
          ))}
          {t.missing_terms.map((x) => (
            <span key={`x-${x}`} className="term term-miss" title="not found in top authorized passages">✗ {x}</span>
          ))}
        </div>
        {t.gaps.length > 0 && (
          <ul className="small gaps">
            {t.gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        )}
      </div>

      {(injectionInQuestion.length > 0 || injectionInSources.length > 0) && (
        <div className="trust-block alert-block" role="alert">
          <h3>⚠ Untrusted instructions detected</h3>
          {injectionInQuestion.length > 0 && (
            <p className="small">
              In your question: {injectionInQuestion.map((m) => <code key={m}>{m}</code>)}. Treated as data, not as instructions.
            </p>
          )}
          {injectionInSources.map((s) => (
            <p key={s.pid} className="small">
              In source <strong>{s.pid}</strong> <span className="mono">{s.ref}</span>: {s.matches.map((m) => <code key={m}>{m}</code>)}. The
              pipeline does not follow text inside documents.
            </p>
          ))}
        </div>
      )}

      <div className="trust-block">
        <h3>Conflicts {t.conflicts.length > 0 && <span className="count count-warn">{t.conflicts.length}</span>}</h3>
        {t.conflicts.length === 0 && <p className="small muted">No conflicting values detected among in-force evidence.</p>}
        {t.conflicts.map((c, i) => (
          <div key={i} className="conflict">
            <div className="small">
              <span className="pill pill-warn">{c.kind}</span> {c.explanation}
            </div>
            <div className="conflict-cols">
              {([
                [c.a, c.a_values],
                [c.b, c.b_values],
              ] as const).map(([cit, vals], j) => (
                <div key={j} className="conflict-side">
                  <div className="conflict-values">
                    {vals.map((v) => (
                      <strong key={v} className="value">{v}</strong>
                    ))}
                  </div>
                  <blockquote className="quote">{cit.quote}</blockquote>
                  <CitationChip c={cit} onOpen={(cc) => onOpenCitation(cc, `Conflict (${c.kind}): ${c.explanation}`)} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {t.amendment_overrides.length > 0 && (
        <div className="trust-block">
          <h3>Amendment overrides</h3>
          <ul className="small">
            {t.amendment_overrides.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="trust-block">
        <h3>Freshness</h3>
        {t.freshness.length === 0 ? (
          <p className="small muted">All cited sources are in force and recent relative to {result.as_of}.</p>
        ) : (
          <ul className="small">
            {t.freshness.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="trust-block">
        <h3>Retrieval diagnostics</h3>
        <p className="small">
          Method <code>{result.retrieval.method}</code> · retrieval {result.retrieval.latency_ms} ms · total {result.latency_ms} ms ·{" "}
          {result.scope.authorized_versions} authorized versions / {result.scope.authorized_chunks} chunks in scope
        </p>
        {result.retrieval.notes.length > 0 && (
          <ul className="small warn-list">
            {result.retrieval.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <div className="table-wrap">
          <table className="table compact">
            <caption className="sr-only">Top retrieval hits with component ranks</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Source</th>
                <th scope="col">Chunk</th>
                {Array.from(new Set(result.retrieval.hits.flatMap((h) => Object.keys(h.components)))).map((k) => (
                  <th key={k} scope="col">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.retrieval.hits.map((h) => (
                <tr key={h.chunk_id}>
                  <td>{h.rank}</td>
                  <td className="mono small">{refByVid.get(h.version_id) ?? `v${h.version_id}`}</td>
                  <td className="mono small">{h.chunk_id}</td>
                  {Array.from(new Set(result.retrieval.hits.flatMap((x) => Object.keys(x.components)))).map((k) => (
                    <td key={k} className="mono small">{h.components[k] ?? "—"}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {result.generation.requested && (
        <div className="trust-block">
          <h3>Generation</h3>
          <p className="small">
            Status: <strong>{result.generation.status ?? "skipped"}</strong>
            {result.generation.model && (
              <>
                {" "}· model <code>{result.generation.model}</code> via {result.generation.provider}
              </>
            )}
            {result.generation.latency_ms != null && <> · {result.generation.latency_ms} ms</>}
          </p>
          {result.generation.rejected_reason && <p className="small warn">Rejected: {result.generation.rejected_reason}</p>}
          {result.generation.prompt_tokens_est != null && (
            <p className="small muted">
              ~{result.generation.prompt_tokens_est} prompt / ~{result.generation.completion_tokens_est} completion tokens.{" "}
              {result.generation.cost_note}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
