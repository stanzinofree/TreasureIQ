"use client";

/**
 * Header pill (v3) — "Stato sistemi", not just "Fonti attive".
 *
 * Sourced from the extended `GET /api/status`, which carries three groups:
 * Fonti (the comuni), Sistemi (TreasureIQ's own components) and Stato dati
 * interni (headline recovery numbers).
 *
 * The label reports *availability* only — the worst of Fonti and Sistemi.
 * Dati interni deliberately stays out of it: those entries measure how open
 * the published data is, so "Fonti sotto piena apertura: 100%" is red by
 * design and says nothing about whether the service is up. Folding it into
 * the label made a healthy system announce itself as "irraggiungibile",
 * which is the exact false alarm this project exists to avoid. It keeps its
 * own dot instead.
 *
 * Every field is nullable and the endpoint itself may be unreachable — a real
 * state, not an error to hide: it renders "non verificato" rather than a
 * spinner that never resolves, the same honest-about-gaps posture as the rest
 * of the app.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { status as fetchStatus, type StatusOut } from "@/lib/api";

type State = "ok" | "degraded" | "down" | "unknown";

const LABEL: Record<State, string> = {
  ok: "Sistemi attivi",
  degraded: "Sistemi in difficoltà",
  down: "Sistemi irraggiungibili",
  unknown: "Stato non verificato",
};

const ORDER: State[] = ["down", "degraded", "ok", "unknown"];

function worst(states: State[]): State {
  if (states.length === 0) return "unknown";
  for (const s of ORDER) if (states.includes(s)) return s;
  return "unknown";
}

const GROUP_LABEL: Record<"fonti" | "sistemi" | "dati", string> = {
  fonti: "Fonti",
  sistemi: "Sistemi",
  dati: "Qualità dei dati",
};

// Screen readers get Italian, not the raw enum: "Dati interni: down" is jargon.
const STATE_LABEL: Record<State, string> = {
  ok: "regolare",
  degraded: "sotto soglia",
  down: "critico",
  unknown: "non verificato",
};

export default function StatusPill() {
  const [data, setData] = useState<StatusOut | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    fetchStatus()
      .then((out) => live && setData(out))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, []);

  const sources = data?.sources ?? null;
  const sistemi = data?.sistemi ?? null;
  const dati = data?.dati_interni ?? null;

  const fontiState: State = sources
    ? worst(sources.map((s) => ((s.records ?? 0) > 0 ? "ok" : "down")))
    : "unknown";
  const sistemiState: State = sistemi
    ? worst(sistemi.map((s) => s.stato))
    : "unknown";
  const datiState: State = dati ? worst(dati.map((d) => d.stato)) : "unknown";

  // Availability only — `datiState` is a data-quality reading, not an outage.
  const overall: State =
    !failed && (sources || sistemi)
      ? worst([fontiState, sistemiState])
      : "unknown";

  const groups: { key: "fonti" | "sistemi" | "dati"; state: State }[] = [
    { key: "fonti", state: fontiState },
    { key: "sistemi", state: sistemiState },
    { key: "dati", state: datiState },
  ];

  const reachableCount = sources?.filter((s) => (s.records ?? 0) > 0).length ?? null;

  // The third dot is often red while the service is perfectly up, so the
  // tooltip has to say what it measures — otherwise it reads as a fault.
  const hint = [
    reachableCount != null && sources != null
      ? `${reachableCount} di ${sources.length} fonti con dati`
      : null,
    datiState === "down" || datiState === "degraded"
      ? "qualità dei dati pubblicati sotto soglia (non è un guasto)"
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Link
      href="/monitoraggio"
      className="status-pill"
      data-overall={overall}
      title={hint ? `${hint} — vai allo stato sistemi` : "Vai allo stato sistemi"}
    >
      <span className="status-pill__dot" aria-hidden="true" />
      <span>{LABEL[overall]}</span>
      <span className="status-pill__dots" aria-label="Stato per gruppo" role="group">
        {groups.map((g) => (
          <span
            key={g.key}
            className="status-pill__dot--sm"
            data-stato={g.state}
            role="img"
            aria-label={`${GROUP_LABEL[g.key]}: ${STATE_LABEL[g.state]}`}
          />
        ))}
      </span>
    </Link>
  );
}
