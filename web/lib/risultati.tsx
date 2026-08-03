"use client";

/**
 * Everything the conversation has turned up so far, plus the filters over it.
 *
 * The cards themselves stay in the chat, attached to the question that
 * produced them — a verdict detached from its question is a verdict without
 * context, and with several questions in a row nothing would tell the reader
 * which answer belonged to which. What lives here is an *index*: one line per
 * opportunity, which scrolls the reader back to the card in the transcript.
 *
 * Filters narrow the index, never the transcript. Hiding a card inside the
 * conversation would silently rewrite what the service already said; hiding a
 * row in a list the reader is actively filtering does not.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { Match, Verdict } from "@/lib/api";

export type Livello = Match["livello"];

export type Trovata = {
  /** Anchor of the card in the transcript, unique per message. */
  ancora: string;
  titolo: string;
  verdict: Verdict;
  verdictLabel: string;
  livello: Livello;
};

type Filtri = {
  livelli: Set<Livello>;
  esiti: Set<Verdict>;
};

type RisultatiContextValue = {
  trovate: Trovata[];
  /** Only those passing the active filters — what the index renders. */
  filtrate: Trovata[];
  filtri: Filtri;
  commutaLivello: (l: Livello) => void;
  commutaEsito: (v: Verdict) => void;
  azzeraFiltri: () => void;
  registra: (nuove: Trovata[]) => void;
  /** Which values actually occur, so the UI never offers an empty filter. */
  livelliPresenti: Livello[];
  esitiPresenti: { verdict: Verdict; label: string }[];
};

const RisultatiContext = createContext<RisultatiContextValue | null>(null);

function commuta<T>(insieme: Set<T>, valore: T): Set<T> {
  const next = new Set(insieme);
  if (next.has(valore)) next.delete(valore);
  else next.add(valore);
  return next;
}

export function RisultatiProvider({ children }: { children: React.ReactNode }) {
  const [trovate, setTrovate] = useState<Trovata[]>([]);
  const [livelli, setLivelli] = useState<Set<Livello>>(new Set());
  const [esiti, setEsiti] = useState<Set<Verdict>>(new Set());

  // Same opportunity asked twice produces two cards, in two different places
  // in the transcript. Both are kept: the index points at positions in the
  // conversation, and collapsing them would leave a row pointing at only one.
  const registra = useCallback((nuove: Trovata[]) => {
    setTrovate((correnti) => {
      const viste = new Set(correnti.map((t) => t.ancora));
      return [...correnti, ...nuove.filter((t) => !viste.has(t.ancora))];
    });
  }, []);

  const commutaLivello = useCallback((l: Livello) => setLivelli((s) => commuta(s, l)), []);
  const commutaEsito = useCallback((v: Verdict) => setEsiti((s) => commuta(s, v)), []);
  const azzeraFiltri = useCallback(() => {
    setLivelli(new Set());
    setEsiti(new Set());
  }, []);

  const value = useMemo<RisultatiContextValue>(() => {
    // An empty filter set means "no constraint", not "match nothing" — the
    // reader who has ticked nothing wants to see everything.
    const filtrate = trovate.filter(
      (t) =>
        (livelli.size === 0 || livelli.has(t.livello)) &&
        (esiti.size === 0 || esiti.has(t.verdict)),
    );

    const livelliPresenti = [...new Set(trovate.map((t) => t.livello))];
    const esitiVisti = new Map<Verdict, string>();
    for (const t of trovate) esitiVisti.set(t.verdict, t.verdictLabel);

    return {
      trovate,
      filtrate,
      filtri: { livelli, esiti },
      commutaLivello,
      commutaEsito,
      azzeraFiltri,
      registra,
      livelliPresenti,
      esitiPresenti: [...esitiVisti].map(([verdict, label]) => ({ verdict, label })),
    };
  }, [trovate, livelli, esiti, commutaLivello, commutaEsito, azzeraFiltri, registra]);

  return <RisultatiContext.Provider value={value}>{children}</RisultatiContext.Provider>;
}

export function useRisultati(): RisultatiContextValue {
  const ctx = useContext(RisultatiContext);
  if (!ctx) {
    throw new Error("useRisultati va usato dentro <RisultatiProvider>");
  }
  return ctx;
}
