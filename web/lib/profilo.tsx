"use client";

/**
 * What the service knows about the citizen, and where each fact came from.
 *
 * This is deliberately not "a user profile". TreasureIQ answers with what the
 * comune published, and the same honesty applies inwards: the citizen should
 * be able to see, at a glance, every fact the answer is being computed from —
 * and nothing should appear here that the citizen did not actually provide.
 *
 * Two rules the rest of the app must not break:
 *
 *   1. Empty means empty. Until a fact is genuinely known the strip renders
 *      nothing at all. Pre-filling a comune "for convenience" would state a
 *      residency the citizen never claimed, which is exactly the failure the
 *      geolocation flow in `Chat` already refuses to make (see `locate`).
 *
 *   2. Provenance travels with the value. A comune inferred from GPS is not
 *      the same fact as a comune the citizen confirmed, so `origine` rides
 *      along and the strip shows the difference instead of flattening it.
 *
 * State is in memory only, for the life of the tab. Nothing is persisted and
 * nothing is sent anywhere on its own — `Chat` already sends what it needs
 * with each question.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";

export type Origine = "dichiarato" | "geolocalizzazione";

export type FattoComune = {
  nome: string;
  istat: string;
  origine: Origine;
  /** GPS says where someone is standing, never where they are resident. */
  confermato: boolean;
  /** Whether we actually ingest this comune's data. A comune the citizen can
   * name but we do not read is a real distinction — the "did my comune
   * publish this?" control only makes sense where the answer can be honest,
   * i.e. where we have snapshots to check against. */
  coperto?: boolean;
};

/** Recapiti letti al volo dal portale di un comune fuori copertura. Nessun
 * numero è verificato. `istat` lega i recapiti al comune, `letto_il` è l'ora del
 * controllo (ISO 8601), `fonte_tipo` è sempre «scansione web». */
export type NumeriUtiliProfilo = {
  istat: string;
  comune: string;
  telefoni: string[];
  email: string[];
  pec: string[];
  fonte: string | null;
  fonteTipo: string;
  lettoIl: string;
};

export type Profilo = {
  nome?: string;
  eta?: number;
  /** Deduced from the first name (D-52), not asked. `sessoDedotto` says so, so
   * the strip can show it is an inference the citizen can correct, not a fact
   * they stated. */
  sesso?: "f" | "m";
  sessoDedotto?: boolean;
  /** The citizen's own disability (or that of the person being asked about),
   * distinct from `disabilitaNucleo` which is a child's. */
  disabilita?: boolean;
  nucleoFamiliare?: number;
  /** A child in the household has a disability (D-53). */
  disabilitaNucleo?: boolean;
  /** How many minor children are in the household. */
  figliMinori?: number;
  comune?: FattoComune;
  /** Recapiti del comune fuori copertura, letti al volo dal portale e mostrati
   * come banner nel pannello. Portano con sé l'ISTAT del comune di cui sono i
   * recapiti: il banner si rende solo se combacia col comune corrente, così un
   * cambio di comune non lascia in vista i numeri di quello precedente. */
  numeriUtili?: NumeriUtiliProfilo;
  interessi?: string[];
};

type ProfiloContextValue = {
  profilo: Profilo;
  /** Merge in newly-learned facts. Undefined values never overwrite known ones. */
  registra: (fatti: Partial<Profilo>) => void;
  /** Drop everything. The citizen can always take it back. */
  dimentica: () => void;
  /** Drop only the comune, keeping everything else.
   *
   * `registra` cannot do this: it deliberately skips `undefined` so a partial
   * update never erases a fact by omission. Saying "no, it's another comune"
   * IS an erasure, and it must not take a name or an age down with it. */
  dimenticaComune: () => void;
  /** Drop a single fact while keeping everything else. */
  dimenticaFatto: (
    campo:
      | "eta"
      | "interessi"
      | "nome"
      | "sesso"
      | "disabilita"
      | "nucleoFamiliare"
      | "disabilitaNucleo"
      | "figliMinori",
  ) => void;
  /** Drop one interest tag without touching the rest of the list. */
  dimenticaInteresse: (tag: string) => void;
  /** How many facts are currently known — drives the empty state. */
  quantiFatti: number;
};

const ProfiloContext = createContext<ProfiloContextValue | null>(null);

function contaFatti(p: Profilo): number {
  return [
    p.nome,
    p.eta,
    p.sesso,
    // I booleani contano solo quando sono veri: un `false` non è un fatto che
    // il servizio "sa", è l'assenza del fatto.
    p.disabilita === true ? true : undefined,
    p.nucleoFamiliare,
    p.disabilitaNucleo === true ? true : undefined,
    p.figliMinori,
    p.comune,
    p.interessi?.length ? p.interessi : undefined,
  ].filter((v) => v !== undefined).length;
}

export function ProfiloProvider({ children }: { children: React.ReactNode }) {
  const [profilo, setProfilo] = useState<Profilo>({});

  const registra = useCallback((fatti: Partial<Profilo>) => {
    setProfilo((corrente) => {
      const next = { ...corrente };
      for (const [chiave, valore] of Object.entries(fatti)) {
        if (valore !== undefined) {
          (next as Record<string, unknown>)[chiave] = valore;
        }
      }
      return next;
    });
  }, []);

  // The profile is local to the tab. Clearing it immediately must not depend
  // on a network call succeeding.
  const dimenticaComune = useCallback(() => {
    setProfilo((corrente) => {
      const next = { ...corrente };
      delete next.comune;
      return next;
    });
  }, []);

  const dimenticaFatto = useCallback(
    (
      campo:
        | "eta"
        | "interessi"
        | "nome"
        | "sesso"
        | "disabilita"
        | "nucleoFamiliare"
        | "disabilitaNucleo"
      | "figliMinori",
    ) => {
      setProfilo((corrente) => {
        const next = { ...corrente };
        delete next[campo];
        // Il sesso porta con sé la sua provenienza: tolto il sesso, la nota
        // "dedotto dal nome" non ha più nulla a cui riferirsi.
        if (campo === "sesso") delete next.sessoDedotto;
        return next;
      });
    },
    [],
  );

  const dimenticaInteresse = useCallback((tag: string) => {
    setProfilo((corrente) => {
      const interessi = corrente.interessi?.filter((i) => i !== tag);
      return { ...corrente, interessi: interessi?.length ? interessi : undefined };
    });
  }, []);

  const dimentica = useCallback(() => {
    setProfilo({});
  }, []);

  const value = useMemo(
    () => ({
      profilo,
      registra,
      dimentica,
      dimenticaComune,
      dimenticaFatto,
      dimenticaInteresse,
      quantiFatti: contaFatti(profilo),
    }),
    [profilo, registra, dimentica, dimenticaComune, dimenticaFatto, dimenticaInteresse],
  );

  return <ProfiloContext.Provider value={value}>{children}</ProfiloContext.Provider>;
}

export function useProfilo(): ProfiloContextValue {
  const ctx = useContext(ProfiloContext);
  if (!ctx) {
    throw new Error("useProfilo va usato dentro <ProfiloProvider>");
  }
  return ctx;
}
