"use client";

import {
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import type { PiattaformaRiga } from "@/lib/api";
import { NEUTRO, nome } from "@/lib/palette";

/** Sotto questa soglia il dato geografico è aneddoto, non distribuzione. */
const MINIMO_COMUNI = 30;

/**
 * Quanto è nazionale un prodotto, e quanto è concentrato.
 *
 * Il conteggio dei comuni non distingue un fornitore diffuso su tutta Italia
 * da una piattaforma che una Regione mette a disposizione dei propri comuni:
 * sono due fenomeni diversi che nella colonna «comuni» hanno lo stesso
 * aspetto. Qui si separano da soli.
 *
 * Sull'asse orizzontale le regioni in cui il prodotto compare, sul verticale
 * quanto pesa nella sua regione principale. In basso a destra i prodotti
 * nazionali; in alto a sinistra le piattaforme regionali, che stanno in una
 * regione sola e lì valgono il cento per cento. La dimensione del punto è il
 * numero di comuni, così il grafico non mente sulle proporzioni.
 */
/**
 * Il riquadro del passaggio del mouse, scritto a mano.
 *
 * Con `formatter` non si puo' fare: in uno scatter il tooltip riceve una voce
 * per ogni asse — orizzontale, verticale e dimensione — quindi il formatter
 * viene chiamato tre volte e la stessa riga compare tre volte, una delle
 * quali con il simbolo di percentuale dell'asse Y appiccicato in coda.
 * Qui il punto e' uno e la riga e' una.
 */
function Riquadro({
  active,
  payload,
}: {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
}) {
  if (!active || !payload?.length) return null;
  const r = payload[0]?.payload as RigaDiffusione | undefined;
  if (!r) return null;
  return (
    <div
      style={{
        background: "var(--paper-raised)",
        border: "1px solid var(--kasumi)",
        borderRadius: 8,
        padding: "8px 12px",
        fontSize: 13,
        maxWidth: 280,
      }}
    >
      <strong>{r.etichetta}</strong>
      <div style={{ color: "var(--sumi-soft)", marginTop: 2 }}>
        {r.comuni} comuni in {r.regioni} {r.regioni === 1 ? "regione" : "regioni"}
      </div>
      <div style={{ color: "var(--sumi-soft)" }}>
        {r.concentrazione}% in {r.regione_prima ?? "—"}
      </div>
    </div>
  );
}

type RigaDiffusione = PiattaformaRiga & { etichetta: string; concentrazione: number };

export function GraficoDiffusione({ righe }: { righe: PiattaformaRiga[] }) {
  const dati = righe
    .filter((r) => r.comuni >= MINIMO_COMUNI && r.piattaforma !== "non_misurata")
    .map((r) => ({
      ...r,
      etichetta: nome(r.piattaforma),
      concentrazione: r.comuni ? Math.round((r.comuni_prima * 100) / r.comuni) : 0,
    }));

  if (!dati.length) return null;

  return (
    <ResponsiveContainer width="100%" height={380}>
      <ScatterChart margin={{ left: 8, right: 24, top: 12, bottom: 28 }}>
        <CartesianGrid stroke="var(--kasumi)" />
        <XAxis
          type="number"
          dataKey="regioni"
          domain={[0, 21]}
          name="regioni"
          tick={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          stroke="var(--kasumi)"
          label={{
            value: "in quante regioni compare",
            position: "insideBottom",
            offset: -16,
            style: { fill: "var(--sumi-soft)", fontSize: 12 },
          }}
        />
        <YAxis
          type="number"
          dataKey="concentrazione"
          domain={[0, 100]}
          unit="%"
          tick={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          stroke="var(--kasumi)"
          label={{
            value: "quota nella regione principale",
            angle: -90,
            position: "insideLeft",
            style: { fill: "var(--sumi-soft)", fontSize: 12 },
          }}
        />
        {/* La dimensione porta il numero di comuni: senza, un prodotto da mille
            comuni e uno da trenta sarebbero due punti identici. */}
        <ZAxis type="number" dataKey="comuni" range={[60, 900]} />
        <Tooltip cursor={{ strokeDasharray: "3 3", stroke: "var(--kasumi)" }} content={Riquadro as never} />
        {/* `line` spento esplicitamente: acceso, Recharts collega i punti in
            ordine di dato e chiude il tracciato, disegnando un rettangolo blu
            attorno all'area del grafico che sembra una cornice e non lo e'. */}
        <Scatter data={dati} line={false} shape="circle" isAnimationActive={false}>
          {dati.map((r) => (
            <Cell
              key={r.piattaforma}
              fill={r.piattaforma === "ignota" ? NEUTRO : "var(--ai)"}
              fillOpacity={0.55}
              stroke="var(--paper)"
              strokeWidth={2}
            />
          ))}
        </Scatter>
      </ScatterChart>
    </ResponsiveContainer>
  );
}
