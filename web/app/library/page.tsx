"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Section } from "@/components/Bits";
import { DocumentInspector, type InspectTarget } from "@/components/DocumentInspector";
import { api, errorText } from "@/lib/api";
import type { DocumentListItem } from "@/lib/types";

export default function LibraryPage() {
  const [rows, setRows] = useState<DocumentListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [collection, setCollection] = useState("");
  const [docType, setDocType] = useState("");
  const [force, setForce] = useState<"" | "in" | "out">("");
  const [text, setText] = useState("");
  const [inspect, setInspect] = useState<{ key: number; target: InspectTarget } | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    let cancelled = false;
    api<DocumentListItem[]>("/api/documents?include_history=true")
      .then((r) => {
        if (!cancelled) setRows(r);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const collections = useMemo(() => [...new Set((rows ?? []).map((r) => r.collection))].sort(), [rows]);
  const types = useMemo(() => [...new Set((rows ?? []).map((r) => r.doc_type))].sort(), [rows]);
  const versionsByKey = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of rows ?? []) m.set(r.doc_key, (m.get(r.doc_key) ?? 0) + 1);
    return m;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = text.trim().toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        (!collection || r.collection === collection) &&
        (!docType || r.doc_type === docType) &&
        (!force || (force === "in" ? r.in_force : !r.in_force)) &&
        (!q || r.title.toLowerCase().includes(q) || r.ref.toLowerCase().includes(q)),
    );
  }, [rows, collection, docType, force, text]);

  const open = (target: InspectTarget) => {
    seq.current += 1;
    setInspect({ key: seq.current, target });
  };

  return (
    <div className="page">
      <Section
        title="Document library"
        kicker="Every version your identity may read"
        actions={rows && <span className="small muted">{filtered.length} of {rows.length} versions</span>}
      >
        <div className="filters">
          <label className="field">
            <span>Collection</span>
            <select value={collection} onChange={(e) => setCollection(e.target.value)}>
              <option value="">All</option>
              {collections.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Type</span>
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              <option value="">All</option>
              {types.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Status</span>
            <select value={force} onChange={(e) => setForce(e.target.value as "" | "in" | "out")}>
              <option value="">Any</option>
              <option value="in">In force</option>
              <option value="out">Historical</option>
            </select>
          </label>
          <label className="field grow">
            <span>Filter by title or ref</span>
            <input type="search" value={text} onChange={(e) => setText(e.target.value)} />
          </label>
        </div>
        {error && <div className="banner banner-error" role="alert">{error}</div>}
        {!rows && !error && <p className="muted" aria-live="polite">Loading documents…</p>}
        {rows && (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">Authorized document versions</caption>
              <thead>
                <tr>
                  <th scope="col">Ref</th>
                  <th scope="col">Title</th>
                  <th scope="col">Collection</th>
                  <th scope="col">Type</th>
                  <th scope="col">Class.</th>
                  <th scope="col">Effective</th>
                  <th scope="col">Status</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.version_id}>
                    <td className="mono small">{r.ref}</td>
                    <td>
                      <button type="button" className="link-btn left" onClick={() => open({ versionId: r.version_id })}>
                        {r.title}
                      </button>
                      {r.amends && <div className="small muted">amends <span className="mono">{r.amends}</span></div>}
                      {r.tags.length > 0 && <div className="small muted">{r.tags.join(", ")}</div>}
                    </td>
                    <td className="small">{r.collection}</td>
                    <td className="small">{r.doc_type}</td>
                    <td className="small">{r.classification}</td>
                    <td className="mono small">{r.effective_date}</td>
                    <td>
                      {r.in_force ? (
                        <span className="pill pill-ok">in force</span>
                      ) : (
                        <span className="pill pill-warn">superseded{r.superseded_by ? ` → v${r.superseded_by}` : ""}</span>
                      )}
                    </td>
                    <td>
                      {(versionsByKey.get(r.doc_key) ?? 0) >= 2 && (
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => open({ versionId: r.version_id, initialTab: "compare" })}>
                          Compare
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="muted">No versions match these filters.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {inspect && <DocumentInspector key={inspect.key} target={inspect.target} onClose={() => setInspect(null)} />}
    </div>
  );
}
