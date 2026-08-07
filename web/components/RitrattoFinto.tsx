/**
 * I ritratti dei profili di prova, disegnati qui dentro.
 *
 * SVG inline e non immagini: nessun file da scaricare, nessuna licenza da
 * rispettare, nessuna richiesta di rete durante una demo, e restano nitidi a
 * qualunque ingrandimento — che in una registrazione dello schermo conta.
 *
 * Volutamente cartoon, e volutamente non fotografici. Una faccia generata che
 * sembra vera darebbe a una persona inventata i lineamenti di qualcuno che
 * esiste: quattro sagome piatte dicono «questo profilo e' finto» senza che
 * nessuno debba leggere l'etichetta.
 */

import type { ReactNode } from "react";

const PELLE = {
  chiara: "#f2d3bb",
  media: "#e8c1a0",
  olivastra: "#c98d68",
  scura: "#8d5a3b",
} as const;

/**
 * Un volto in tre strati, ed e' l'unica cosa che conta qui dentro: quello che
 * sta dietro la testa (capelli lunghi, spalle), la testa, e quello che sta
 * davanti (frangia, occhiali). Disegnati tutti insieme, gli occhiali di un
 * pensionato finivano sotto la faccia — cioe' invisibili.
 */
function Volto({
  pelle,
  dietro,
  davanti,
}: {
  pelle: string;
  dietro?: ReactNode;
  davanti?: ReactNode;
}) {
  return (
    <svg viewBox="0 0 60 80" role="img" aria-hidden="true" focusable="false">
      <rect width="60" height="80" fill="#eef2f7" />
      {dietro}
      <circle cx="30" cy="34" r="15" fill={pelle} />
      <circle cx="25" cy="33" r="1.6" fill="#20303f" />
      <circle cx="35" cy="33" r="1.6" fill="#20303f" />
      <path
        d="M26 40 q4 3.5 8 0"
        stroke="#20303f"
        strokeWidth="1.4"
        strokeLinecap="round"
        fill="none"
      />
      {davanti}
    </svg>
  );
}

/** Le spalle: una cupola che esce dal bordo inferiore, come in una foto. */
function Spalle({ colore }: { colore: string }) {
  return <path d="M6 80 q24 -24 48 0 z" fill={colore} />;
}

const RITRATTI: Record<string, ReactNode> = {
  famiglia: (
    <Volto
      pelle={PELLE.chiara}
      dietro={
        <>
          <Spalle colore="#5b8c7b" />
          {/* Caschetto: la massa dietro, con i due lati che scendono. */}
          <path d="M13 36 q0 -22 17 -22 q17 0 17 22 l0 12 q-4 -6 -4 -14 l-26 0 q0 8 -4 14 z" fill="#3a2f2a" />
        </>
      }
      davanti={
        /* La frangia sta davanti, se no sparisce sotto la faccia. */
        <path d="M15 28 q3 -10 15 -10 q12 0 15 10 q-8 -4 -15 -4 q-7 0 -15 4 z" fill="#3a2f2a" />
      }
    />
  ),
  pensionato: (
    <Volto
      pelle={PELLE.media}
      dietro={
        <>
          <Spalle colore="#6b7a99" />
          <path d="M15 32 q1 -17 15 -17 q14 0 15 17 q-6 -10 -15 -10 q-9 0 -15 10 z" fill="#c9ced6" />
        </>
      }
      davanti={
        <g stroke="#54607a" strokeWidth="1.3" fill="none">
          <circle cx="25" cy="33" r="4.8" />
          <circle cx="35" cy="33" r="4.8" />
          <path d="M29.8 33 h0.4" />
          <path d="M20.2 32 l-3 -1" strokeLinecap="round" />
          <path d="M39.8 32 l3 -1" strokeLinecap="round" />
        </g>
      }
    />
  ),
  studente: (
    <Volto
      pelle={PELLE.olivastra}
      dietro={
        <>
          <Spalle colore="#c98b4b" />
          <g fill="#2b2118">
            <circle cx="21" cy="24" r="8" />
            <circle cx="30" cy="19" r="9" />
            <circle cx="39" cy="24" r="8" />
          </g>
        </>
      }
      davanti={
        <g fill="#2b2118">
          <circle cx="22" cy="24" r="4.5" />
          <circle cx="30" cy="22" r="5" />
          <circle cx="38" cy="24" r="4.5" />
        </g>
      }
    />
  ),
  capofamiglia: (
    <Volto
      pelle={PELLE.scura}
      dietro={
        <>
          <Spalle colore="#8a5f8f" />
          {/* Capelli lunghi raccolti: chignon dietro la testa. */}
          <circle cx="30" cy="15" r="6" fill="#241c1a" />
          <path d="M13 42 q0 -28 17 -28 q17 0 17 28 l0 6 q-5 -10 -5 -20 l-24 0 q0 10 -5 20 z" fill="#241c1a" />
        </>
      }
      davanti={
        <path d="M15 27 q4 -9 15 -9 q11 0 15 9 q-9 -3 -15 -3 q-6 0 -15 3 z" fill="#241c1a" />
      }
    />
  ),
};

export default function RitrattoFinto({ id }: { id: string }) {
  return (
    <span className="tessera__ritratto">
      {RITRATTI[id] ?? <Volto pelle={PELLE.media} dietro={<Spalle colore="#8c95a3" />} />}
    </span>
  );
}
