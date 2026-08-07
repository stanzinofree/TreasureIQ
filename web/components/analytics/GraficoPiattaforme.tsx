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

import type { PiattaformaRiga } from "@/lib/api";
import { NEUTRO, nome } from "@/lib/palette";

/** Cio' che non e' un fornitore: assenza di dato, non una categoria in gara. */
const SENZA_TINTA = new Set(["ignota", "non_misurata"]);

/**
 * Quanti comuni girano su ogni piattaforma.
 *
 * Una tinta sola per tutte le barre, e non per poverta' di palette: qui il
 * colore non ha un mestiere. L'identita' di ciascuna piattaforma sta gia'
 * scritta sull'asse, e venti tinte chiederebbero al lettore di imparare una
 * legenda per leggere un dato che sa gia' leggere.
 *
 * La versione precedente colorava le prime cinque e raggruppava il resto in
 * «altre», che a furia di riconoscere piattaforme era diventato il gruppo piu'
 * grande del grafico: il colore costringeva a nascondere proprio la parte
 * appena scoperta. Tolto il colore, cade il motivo di nascondere.
 *
 * Restano in grigio i non riconosciuti e i non misurati, perche' li' il colore
 * un mestiere ce l'ha: dire che non sono un fornitore.
 */
export function GraficoPiattaforme({ righe }: { righe: PiattaformaRiga[] }) {
  const dati = righe.map((r) => ({ ...r, etichetta: nome(r.piattaforma) }));
  // 34px per barra: sotto, Recharts nasconde un'etichetta su due per non
  // sovrapporle, e meta' delle barre resta senza nome.
  const altezza = Math.max(260, dati.length * 34);

  return (
    <ResponsiveContainer width="100%" height={altezza}>
      <BarChart data={dati} layout="vertical" margin={{ left: 8, right: 56, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke="var(--kasumi)" />
        <XAxis
          type="number"
          tick={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          stroke="var(--kasumi)"
        />
        <YAxis
          type="category"
          dataKey="etichetta"
          width={215}
          // Tutte le etichette, sempre: l'identita' qui e' solo sull'asse,
          // quindi una barra senza etichetta non e' leggibile affatto.
          interval={0}
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
          formatter={(valore, _nome, voce) => {
            const r = (voce as { payload: PiattaformaRiga }).payload;
            const dove =
              r.regioni > 1
                ? ` · ${r.regioni} regioni`
                : r.regione_prima
                  ? ` · solo ${r.regione_prima}`
                  : "";
            const cat = r.servizi ? ` · ${r.servizi.toLocaleString("it-IT")} servizi letti` : "";
            return [`${String(valore)} comuni${dove}${cat}`, ""] as [string, string];
          }}
        />
        <Bar dataKey="comuni" barSize={14} radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {dati.map((r) => (
            <Cell
              key={r.piattaforma}
              fill={SENZA_TINTA.has(r.piattaforma) ? NEUTRO : "var(--ai)"}
            />
          ))}
          <LabelList
            dataKey="comuni"
            position="right"
            style={{ fill: "var(--sumi-soft)", fontSize: 12 }}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
