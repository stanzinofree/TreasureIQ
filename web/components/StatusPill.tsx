"use client";

/**
 * Header pill — one indicator, one meaning: is the service up?
 *
 * `GET /api/status` carries three groups (Fonti, Sistemi, Stato dati interni)
 * and the pill used to show a dot for each. That was three questions asked in
 * a corner of the masthead, and the third one has no business being there:
 * "Fonti sotto piena apertura: 100%" measures how openly comuni publish their
 * data, so it is red today, will stay red until they open it, and says nothing
 * about whether anything is working. A permanent red dot next to a working
 * service teaches people to ignore the indicator.
 *
 * So the pill answers availability only — the worst of Fonti and Sistemi — and
 * `/monitoraggio` carries the breakdown, including the data-openness figures
 * that belong in a report rather than in a status light.
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

  const fontiState: State = sources
    ? worst(sources.map((s) => ((s.records ?? 0) > 0 ? "ok" : "down")))
    : "unknown";
  const sistemiState: State = sistemi
    ? worst(sistemi.map((s) => s.stato))
    : "unknown";

  const overall: State =
    !failed && (sources || sistemi) ? worst([fontiState, sistemiState]) : "unknown";

  const reachableCount = sources?.filter((s) => (s.records ?? 0) > 0).length ?? null;
  const hint =
    reachableCount != null && sources != null
      ? `${reachableCount} di ${sources.length} fonti con dati — vai al monitoraggio`
      : "Vai al monitoraggio";

  return (
    <Link href="/monitoraggio" className="status-pill" data-overall={overall} title={hint}>
      <span className="status-pill__dot" aria-hidden="true" />
      <span>{LABEL[overall]}</span>
    </Link>
  );
}
