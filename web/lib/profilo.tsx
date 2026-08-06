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
import { dimenticaCampo as dimenticaCampoServer, logout } from "@/lib/api";

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
  /** Drop only the comune, keeping everything else.
   *
   * `registra` cannot do this: it deliberately skips `undefined` so a partial
   * update never erases a fact by omission. Saying "no, it's another comune"
   * IS an erasure, and it must not take a name or an age down with it. */
  dimenticaComune: () => void;
  /** Drop a single fact — età, interessi (the whole list) or nome — keeping
   * everything else, same reasoning as `dimenticaComune`. If a session is
   * open, the server has to be told too: without it, the verdict keeps being
   * computed from a fact the strip no longer shows (R-F). */
  dimenticaFatto: (campo: "eta" | "interessi" | "nome") => void;
  /** Drop one interest tag without touching the rest of the list. */
  dimenticaInteresse: (tag: string) => void;
  /** How many facts are currently known — drives the empty state. */
  quantiFatti: number;
};

/** Unset one fact on the live server session, in place.
 *
 * A full re-`login()` was the first attempt here and it was wrong: the
 * server rebuilds the profile from `LoginRequest` defaults, so replaying it
 * after a removal silently reinstates fields the citizen never touched
 * (`nucleo_familiare` back to the concrete `1`, not back to "unknown") and
 * an engine None-guard that should fire on the untouched field never does.
 * `dimenticaCampo` mutates the existing signed profile instead — every field
 * but the one named here keeps its current value.
 *
 * `valore` is only meaningful for campo "interessi", to drop one tag rather
 * than the whole list. */
function dimenticaCampoSessione(campo: string, valore?: string): void {
  dimenticaCampoServer(campo, valore).catch(() => {
    /* best-effort correction — a failed call cannot re-add the fact the
       citizen just asked to remove, so there is nothing to roll back */
  });
}

const ProfiloContext = createContext<ProfiloContextValue | null>(null);

/** Whether this load of the application has already cleared its session.
 *
 * Module scope on purpose: it outlives every client-side navigation and is
 * reset only by a real page load, which is precisely the line between
 * "arriving" and "moving around inside". */
let giaAzzerato = false;

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

  // Dropping only the local copy left the signed cookie in place, so the
  // interface claimed to know nothing while every answer was still being
  // computed from the comune — the same contradiction as the missing
  // rehydration, in the other direction. The local state is cleared first
  // and regardless: a failed network call must not leave the citizen looking
  // at data they just asked to be rid of.
  const dimenticaComune = useCallback(() => {
    setProfilo((corrente) => {
      if (corrente.accesso) dimenticaCampoSessione("comune");
      const next = { ...corrente };
      delete next.comune;
      return next;
    });
  }, []);

  const dimenticaFatto = useCallback((campo: "eta" | "interessi" | "nome") => {
    setProfilo((corrente) => {
      // "nome" is client-only — CitizenProfile carries no such field, so
      // there is nothing to correct server-side.
      if (corrente.accesso && campo !== "nome") dimenticaCampoSessione(campo);
      const next = { ...corrente };
      delete next[campo];
      return next;
    });
  }, []);

  const dimenticaInteresse = useCallback((tag: string) => {
    setProfilo((corrente) => {
      if (corrente.accesso) dimenticaCampoSessione("interessi", tag);
      const interessi = corrente.interessi?.filter((i) => i !== tag);
      return { ...corrente, interessi: interessi?.length ? interessi : undefined };
    });
  }, []);

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
    // Once per load of the application, not once per visit to this page.
    //
    // This provider lives on the chat page, so it also mounts every time the
    // reader navigates *back* to the chat from anywhere else in the site — and
    // logging out there meant that signing in, going to /opportunita and
    // returning to ask another question silently ended the session. The next
    // page then rendered empty and looked broken, which is exactly how this
    // was found.
    //
    // A module-level flag survives client-side navigation and dies with a real
    // page load, which is the distinction wanted: arriving at the application
    // means arriving as nobody; moving around inside it does not.
    if (giaAzzerato) return;
    giaAzzerato = true;
    logout().catch(() => {
      /* nothing to end — already the clean slate we wanted */
    });
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
