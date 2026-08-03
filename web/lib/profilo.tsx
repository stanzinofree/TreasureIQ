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

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { logout } from "@/lib/api";

export type Origine = "dichiarato" | "geolocalizzazione" | "accesso";

export type FattoComune = {
  nome: string;
  istat: string;
  origine: Origine;
  /** GPS says where someone is standing, never where they are resident. */
  confermato: boolean;
};

export type Profilo = {
  nome?: string;
  eta?: number;
  comune?: FattoComune;
  interessi?: string[];
  /**
   * Present only when a real authenticated session supplies it. The SPID/CIE
   * flow in this build is a simulation and produces no codice fiscale, so this
   * stays undefined rather than being filled with a plausible-looking string:
   * a fabricated identifier shown back to a citizen as their own is worse than
   * no identifier at all.
   */
  codiceFiscale?: string;
  /** True once the citizen has authenticated, with or without a CF. */
  accesso?: boolean;
};

type ProfiloContextValue = {
  profilo: Profilo;
  /** Merge in newly-learned facts. Undefined values never overwrite known ones. */
  registra: (fatti: Partial<Profilo>) => void;
  /** Drop everything. The citizen can always take it back. */
  dimentica: () => void;
  /** How many facts are currently known — drives the empty state. */
  quantiFatti: number;
};

const ProfiloContext = createContext<ProfiloContextValue | null>(null);

function contaFatti(p: Profilo): number {
  return [
    p.nome,
    p.eta,
    p.comune,
    p.interessi?.length ? p.interessi : undefined,
    p.codiceFiscale,
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

  // Clearing the strip has to end the session too. Dropping only the local
  // copy left the signed cookie in place, so the interface claimed to know
  // nothing while every answer was still being computed from the profile —
  // the same contradiction as the missing rehydration, in the other
  // direction. The local state is cleared first and regardless: a failed
  // network call must not leave the citizen looking at data they just asked
  // to be rid of.
  const dimentica = useCallback(() => {
    setProfilo({});
    logout().catch(() => {
      /* already logged out, or offline — the local state is gone either way */
    });
  }, []);

  // Arriving means arriving as nobody.
  //
  // This used to rehydrate from /api/me, which fixed one contradiction and
  // created a worse one: the signed cookie lasts eight hours, so opening the
  // chat greeted a visitor with an age and a comune they had not given in
  // this visit — the service recognising someone who never introduced
  // themselves, which is exactly what the product promises not to do.
  //
  // Ending the session instead of reading it keeps the two sides honest in
  // the other direction: nothing is known here, and nothing is known on the
  // server either, so no answer can quietly be shaped by a profile the strip
  // is not showing. Identity is re-established by signing in, which takes one
  // click and is the moment the citizen actually chooses it.
  useEffect(() => {
    logout().catch(() => {
      /* nothing to end — already the clean slate we wanted */
    });
  }, []);

  const value = useMemo(
    () => ({ profilo, registra, dimentica, quantiFatti: contaFatti(profilo) }),
    [profilo, registra, dimentica],
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
