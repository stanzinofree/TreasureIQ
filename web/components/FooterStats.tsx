"use client";

/**
 * Footer vital signs (B14) — sourced from `GET /api/stats`.
 *
 * These numbers are the project's argument in miniature: how much of the
 * public data actually got measured, and what it costs to recover. Every
 * field is independently nullable (another arm is building the endpoint
 * concurrently), so each stat is rendered only when present — a missing
 * measurement must read as absent, never as a confident zero.
 */

import { useEffect, useState } from "react";
import { stats as fetchStats, type StatsOut } from "@/lib/api";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <span className="footer-stat__value">{value}</span>
      <span className="footer-stat__label">{label}</span>
    </div>
  );
}

export default function FooterStats() {
  const [data, setData] = useState<StatsOut | null>(null);

  useEffect(() => {
    let live = true;
    fetchStats()
      .then((out) => live && setData(out))
      .catch(() => {
        /* Endpoint absent or unreachable: the footer simply omits the
           numbers rather than showing an error — these are metrics, not a
           feature the citizen depends on to get an answer. */
      });
    return () => {
      live = false;
    };
  }, []);

  if (!data) return null;

  const stats: { value: string; label: string }[] = [];

  if (data.records_total != null) {
    stats.push({
      value: data.records_total.toLocaleString("it-IT"),
      label:
        data.comuni_measured != null
          ? `record su ${data.comuni_measured} comuni`
          : "record analizzati",
    });
  }
  if (data.avg_recovery_seconds != null) {
    stats.push({
      value: `${Math.round(data.avg_recovery_seconds)} s`,
      label: "tempo medio di recupero",
    });
  }
  if (data.sources_below_full_openness_pct != null) {
    stats.push({
      value: `${Math.round(data.sources_below_full_openness_pct)}%`,
      label: "fonti sotto la piena apertura",
    });
  }
  if (data.requirements_verified != null) {
    stats.push({
      value: data.requirements_verified.toLocaleString("it-IT"),
      label: "requisiti verificati",
    });
  }

  if (stats.length === 0 && data.app_version == null) return null;

  return (
    <div className="footer-stats">
      {stats.length > 0 && (
        <div className="footer-stats__grid">
          {stats.map((s) => (
            <Stat key={s.label} value={s.value} label={s.label} />
          ))}
        </div>
      )}
      <p style={{ fontSize: "0.82rem", color: "var(--sumi-faint)" }}>
        TreasureIQ{data.app_version ? ` · v${data.app_version}` : ""}
      </p>
    </div>
  );
}
