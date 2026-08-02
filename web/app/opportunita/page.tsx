"use client";

/**
 * The citizen's feed.
 *
 * Every card leads with the seal, because the shape of the answer matters more
 * than its wording: a broken ring tells someone at a glance that the comune's
 * data ran out. The per-criterion breakdown is open by default rather than
 * hidden behind a disclosure — the reason a verdict landed the way it did is
 * the product, and burying it would leave a citizen with a verdict they cannot
 * check.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { Seal } from "@/components/Seal";
import { opportunities, me, type Match, type Profile } from "@/lib/api";

const GLYPH: Record<string, string> = {
  met: "●",
  not_met: "✕",
  unknown_source: "◐",
  unknown_profile: "◌",
};

function Card({ match }: { match: Match }) {
  const decided = match.criteria.filter(
    (c) => c.state === "met" || c.state === "not_met",
  );
  // Missing because the comune never published it — nothing the citizen can do.
  const unpublished = match.criteria.filter((c) => c.state === "unknown_source");
  // Missing because the citizen hasn't told us — actionable, so kept separate
  // and shown last, where an action belongs.
  const askProfile = match.criteria.filter((c) => c.state === "unknown_profile");

  return (
    <article className="card" data-verdict={match.verdict}>
      <Seal verdict={match.verdict} size={72} />
      <div>
        <h3 className="card__title">{match.title}</h3>
        <p className="card__headline">{match.headline}</p>

        <div className="card__meta">
          <span className="tag">{match.verdict_label}</span>
          <span>{match.kind.replace(/_/g, " ")}</span>
          {match.deadline && <span>scade il {match.deadline}</span>}
          <span>
            requisiti {match.confidence === "declared" ? "dichiarati" : "dedotti dal testo"}
          </span>
        </div>

        {/* Criteria the engine could evaluate are listed individually — each
            one is a distinct fact about this citizen. Criteria the comune
            simply did not publish are collapsed into a single line: repeating
            the same "not published" sentence six times buries the four facts
            that actually matter under boilerplate. */}
        <ul className="criteria">
          {decided.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}

          {unpublished.length > 0 && (
            <li className="criterion" data-state="unknown_source">
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH.unknown_source}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>
                  Non pubblicati dal comune:
                </strong>{" "}
                {unpublished.map((c) => c.label.toLowerCase()).join(", ")}. Non
                sappiamo se ti riguardano.
              </span>
            </li>
          )}

          {askProfile.map((c) => (
            <li key={c.key} className="criterion" data-state={c.state}>
              <span className="criterion__glyph" aria-hidden="true">
                {GLYPH[c.state]}
              </span>
              <span>
                <strong style={{ fontWeight: 600 }}>{c.label}.</strong> {c.detail}
              </span>
            </li>
          ))}
        </ul>

        {match.notes.length > 0 && (
          <div className="notice">
            {match.notes.map((n, i) => (
              <p key={i} style={{ margin: i ? "var(--ma-2) 0 0" : 0 }}>
                {n}
              </p>
            ))}
          </div>
        )}

        <p style={{ marginTop: "var(--ma-4)", fontSize: "0.9rem" }}>
          <a href={match.source_url} target="_blank" rel="noreferrer">
            Apri la pagina ufficiale del comune →
          </a>
        </p>
      </div>
    </article>
  );
}

export default function Feed() {
  const [items, setItems] = useState<Match[] | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    Promise.all([me(), opportunities(showExcluded)])
      .then(([p, m]) => {
        if (!live) return;
        setProfile(p);
        setItems(m);
      })
      .catch(() => live && setError("session"));
    return () => {
      live = false;
    };
  }, [showExcluded]);

  if (error === "session") {
    return (
      <div className="panel">
        <h2>Sessione non attiva</h2>
        <p className="lede">
          Torna alla pagina iniziale e scegli un profilo per vedere le tue
          opportunità.
        </p>
        <p style={{ marginTop: "var(--ma-6)" }}>
          <Link className="button" href="/">
            Scegli un profilo
          </Link>
        </p>
      </div>
    );
  }

  const counts = items?.reduce<Record<string, number>>((acc, m) => {
    acc[m.verdict] = (acc[m.verdict] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="stack">
      <section>
        <p className="eyebrow">
          {profile ? `${profile.comune_nome} · ${profile.eta} anni` : "Caricamento"}
        </p>
        <h1>Le tue opportunità</h1>
        {items && (
          <p className="lede">
            {items.length} servizi analizzati.{" "}
            {counts?.eligible
              ? `${counts.eligible} confermati, `
              : "Nessuno può essere confermato con i dati pubblicati, "}
            {counts?.likely ?? 0} da verificare sulla pagina del comune.
          </p>
        )}
      </section>

      <label
        style={{
          display: "flex",
          gap: "var(--ma-3)",
          alignItems: "center",
          fontSize: "0.94rem",
        }}
      >
        <input
          type="checkbox"
          checked={showExcluded}
          onChange={(e) => setShowExcluded(e.target.checked)}
        />
        Mostra anche i servizi da cui sei escluso, con il motivo
      </label>

      {items === null && !error && <p>Sto leggendo i dati del comune…</p>}

      <div className="feed">
        {items?.map((m) => (
          <Card key={m.id} match={m} />
        ))}
      </div>

      {items?.length === 0 && (
        <div className="panel">
          <h2>Nessun servizio da mostrare</h2>
          <p className="lede">
            Nessuno dei servizi pubblicati dal comune corrisponde a questo
            profilo. Prova ad attivare i servizi esclusi per vedere quali
            requisiti non sono soddisfatti.
          </p>
        </div>
      )}
    </div>
  );
}
