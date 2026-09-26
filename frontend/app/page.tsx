"use client";

import { useEffect, useState } from "react";

const BFF = process.env.NEXT_PUBLIC_BFF_URL ?? "http://localhost:8000";

// Phase 1 fills this list. Sign-in links are rendered from it so a new
// provider is one entry here and one entry in bff/app/providers.py.
const PROVIDERS: { id: string; label: string }[] = [{ id: "google", label: "Google" }];

type Health = { status: "checking" } | { status: "ok" } | { status: "down"; detail: string };

export default function Home() {
  const [health, setHealth] = useState<Health>({ status: "checking" });

  useEffect(() => {
    // credentials: "include" is what the real /auth/me call will use, so this
    // smoke test exercises the BFF's CORS configuration, not just reachability.
    fetch(`${BFF}/health`, { credentials: "include" })
      .then((r) => (r.ok ? setHealth({ status: "ok" }) : setHealth({ status: "down", detail: `HTTP ${r.status}` })))
      .catch((e: Error) => setHealth({ status: "down", detail: e.message }));
  }, []);

  return (
    <main>
      <h1>OAuth 2.0 / OIDC lab</h1>
      <p className="muted">Phase 0 scaffold. The browser holds no tokens, only a cookie the BFF sets later.</p>

      <div className="card">
        <p>
          BFF at <code>{BFF}</code>:{" "}
          {health.status === "checking" && <span className="muted">checking…</span>}
          {health.status === "ok" && <span className="ok">reachable, CORS ok</span>}
          {health.status === "down" && <span className="bad">unreachable ({health.detail})</span>}
        </p>
        <p className="muted">
          If this says unreachable, start the BFF with <code>uv run uvicorn app.main:app --port 8000</code> in <code>bff/</code>.
        </p>
      </div>

      <div className="card">
        {PROVIDERS.length === 0 ? (
          <p className="muted">No sign-in providers yet. Phase 1 adds Google here.</p>
        ) : (
          PROVIDERS.map((p) => (
            <p key={p.id}>
              {/* A plain link on purpose: OAuth redirects the whole window, fetch() cannot. */}
              <a href={`${BFF}/auth/${p.id}/login`}>Sign in with {p.label}</a>
            </p>
          ))
        )}
      </div>
    </main>
  );
}
