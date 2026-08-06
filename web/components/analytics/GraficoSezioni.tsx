"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SezioneRiga } from "@/lib/api";
import { sezione } from "@/lib/palette";

/** Le sezioni senza cui un cittadino non può agire. */
const CRITICHE = new Set(["a_chi_e_rivolto", "cosa_serve", "tempi_e_scadenze", "come_fare"]);

/**
 * Quali sezioni del modello AgID mancano più spesso.
 *
 * Una sola serie, quindi niente legenda: il titolo la nomina già. Le sezioni
 * critiche sono in rosso di stato — qui il colore *significa* davvero
 * "bloccante", che è l'uso per cui quel token esiste, e non un'identità.
 */
export function GraficoSezioni({ righe }: { righe: SezioneRiga[] }) {
  const dati = righe
    .filter((r) => r.manca_su > 0)
    .map((r) => ({
      ...r,
      etichetta: sezione(r.sezione),
      critica: CRITICHE.has(r.sezione),
      quota: r.misurati ? Math.round((r.manca_su * 100) / r.misurati) : 0,
    }));

  if (!dati.length) {
    return <p className="vuoto">Nessuna scheda misurata: non c'è ancora niente da contare.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, dati.length * 32)}>
      <BarChart data={dati} layout="vertical" margin={{ left: 8, right: 56, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke="var(--kasumi)" />
        <XAxis
          type="number"
          domain={[0, 100]}
          unit="%"
          tick={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          stroke="var(--kasumi)"
        />
        <YAxis
          type="category"
          dataKey="etichetta"
          width={170}
          tick={{ fill: "var(--sumi)", fontSize: 12 }}
          stroke="var(--kasumi)"
        />
        <Tooltip
          cursor={{ fill: "var(--kasumi)", fillOpacity: 0.35 }}
          contentStyle={{
            background: "var(--paper-raised)",
            border: "1px solid var(--kasumi)",
            borderRadius: 8,
            fontSize: 13,
          }}
          formatter={(_valore, _nome, voce) => {
            const r = (voce as { payload: (typeof dati)[number] }).payload;
            return [
              `manca su ${r.manca_su} portali di ${r.misurati} misurati`,
              "",
            ] as [string, string];
          }}
        />
        <Bar dataKey="quota" barSize={16} radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {dati.map((r) => (
            <Cell key={r.sezione} fill={r.critica ? "var(--shu)" : "var(--sumi-soft)"} />
          ))}
          <LabelList
            dataKey="quota"
            position="right"
            formatter={(v) => `${String(v)}%`}
            style={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
