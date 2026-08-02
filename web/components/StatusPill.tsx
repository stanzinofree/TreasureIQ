"use client";

/**
 * Header status pill (B14) — a compact read on whether the comuni's data is
 * currently reachable, sourced from `GET /api/status`.
 *
 * Every field in the contract is nullable, and the endpoint itself may not
 * exist yet or may be unreachable — this is a real state, not an error to
 * hide: it renders as "non verificato", the same honest-about-gaps posture
 * as the rest of the app, rather than a spinner that never resolves.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { status as fetchStatus, type StatusOut } from "@/lib/api";

const LABEL: Record<"ok" | "degraded" | "down" | "unknown", string> = {
  ok: "Fonti attive",
  degraded: "Fonti in difficoltà",
  down: "Fonti irraggiungibili",
  unknown: "Stato non verificato",
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

  const overall = !failed && data?.overall ? data.overall : "unknown";
  const sources = data?.sources ?? null;
  const reachableCount = sources?.filter((s) => s.reachable === true).length ?? null;
  const total = sources?.length ?? null;

  return (
    <Link
      href="/monitoraggio"
      className="status-pill"
      data-overall={overall}
      title={
        reachableCount != null && total != null
          ? `${reachableCount} di ${total} fonti raggiungibili — vai al monitoraggio`
          : "Vai al monitoraggio delle fonti"
      }
    >
      <span className="status-pill__dot" aria-hidden="true" />
      {LABEL[overall]}
    </Link>
  );
}
