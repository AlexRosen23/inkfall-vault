"use client";

import { useEffect, useMemo, useState } from "react";
import { api, errorText } from "@/lib/api";
import type { Identity } from "@/lib/types";

export default function LoginPage() {
  const [identities, setIdentities] = useState<Identity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<Identity[]>("/api/identities")
      .then((rows) => {
        if (!cancelled) setIdentities(rows);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(errorText(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tenants = useMemo(() => {
    const groups = new Map<string, { name: string; people: Identity[] }>();
    for (const i of identities ?? []) {
      const g = groups.get(i.tenant) ?? { name: i.tenant_name, people: [] };
      g.people.push(i);
      groups.set(i.tenant, g);
    }
    return [...groups.entries()];
  }, [identities]);

  const login = async (username: string) => {
    setBusy(username);
    setError(null);
    try {
      await api("/api/auth/login", { body: { username } });
      // Full navigation so the shell loads this identity from scratch.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- deliberate full reload: drop all in-memory state from the previous identity
      window.location.assign("/");
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  };

  return (
    <div className="login-page">
      <div className="login-head">
        <h1>
          <span className="brand-mark" aria-hidden="true">◆</span> The Inkfall Vault
        </h1>
        <p className="lede">A permission-aware evidence workbench. Choose who you are; the server decides what you may see.</p>
        <div className="banner banner-warn" role="note">
          Demo fixture login — fictional identities, no passwords, local use only.
        </div>
      </div>
      {error && <div className="banner banner-error" role="alert">{error}</div>}
      {!identities && !error && <p className="muted" aria-live="polite">Loading identities…</p>}
      <div className="tenant-grid">
        {tenants.map(([tenant, g]) => (
          <section key={tenant} className="panel tenant-card" aria-labelledby={`t-${tenant}`}>
            <h2 id={`t-${tenant}`}>{g.name}</h2>
            <p className="muted mono small">{tenant}</p>
            <ul className="identity-list">
              {g.people.map((p) => (
                <li key={p.username}>
                  <button
                    type="button"
                    className="identity-btn"
                    onClick={() => login(p.username)}
                    disabled={busy !== null}
                    aria-busy={busy === p.username}
                  >
                    <span className="identity-name">{p.display_name}</span>
                    <span className="identity-title">{p.title}</span>
                    <span className="chips-inline">
                      {p.roles.map((r) => (
                        <span key={r} className={r === "admin" || r === "reviewer" ? "pill pill-brass" : "pill"}>{r}</span>
                      ))}
                      <span className="mono small muted">{p.username}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
