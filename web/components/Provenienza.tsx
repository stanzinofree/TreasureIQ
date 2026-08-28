"use client";

/**
 * Grammatica fonti condivisa (slice S2). Un solo posto decide come si legge la
 * provenienza di un dato in chat, così i quattro render vivi
 * (RispostaCivica, SchedaLettoOra, BandiComune, DataGapNotice) parlano la
 * stessa lingua invece di reinventarla ognuno col proprio markup «letto ora».
 *
 * Tre assi tenuti SEPARATI e tutti VISIBILI (D-19, dottrina «un solo bollo»):
 *   - PROVENIENZA → il chip colorato. È l'UNICA cosa colorata/bordata: il
 *     colore dice DA DOVE arriva il dato (catalogo blu, portale live verde,
 *     assente grigio).
 *   - STATO (completezza) → testo neutro accanto al chip («· ufficiale»), mai
 *     un secondo badge colorato. Visibile, ma un dato non diventa un verdetto
 *     per il fatto di avere un'etichetta. Resta anche in `data-stato` sul chip
 *     per semantica/styling/test.
 *   - FRESCHEZZA → riga caption a parte (<Freschezza>), col prefisso giusto per
 *     il render, mai fusa nel chip.
 *
 * Non è un diritto d'accesso: dice la fonte, non se il cittadino è autorizzato.
 */

import { useState } from "react";
import type { InfoOut } from "@/lib/api";
import { accessLabel } from "@/lib/access";
import { dataLeggibile } from "@/lib/date";

type StatoFonte = InfoOut["stato"] | "unavailable";

/** Etichetta del chip quando NON c'è provenienza esplicita (rail informativo
 *  fuori dal connettore servizi) o quando il dato manca. */
const ETICHETTA_CHIP_STATO: Record<StatoFonte, string> = {
  ufficiale: "Fonte ufficiale",
  parziale: "Fonte parziale",
  non_verificato: "Ricerca web",
  non_pubblicato: "Niente di pubblicato",
  unavailable: "Fonte non disponibile",
};

/** Etichetta leggera dello stato, come testo neutro accanto al chip. Niente
 *  «Fonte», niente colore: è completezza, non provenienza. `unavailable` non
 *  ha un secondo stato (il chip stesso già dice «Fonte non disponibile»). */
const ETICHETTA_STATO_NEUTRA: Record<Exclude<StatoFonte, "unavailable">, string> = {
  ufficiale: "ufficiale",
  parziale: "parziale",
  non_verificato: "non verificato",
  non_pubblicato: "non pubblicato",
};

/** La riga di freschezza: quando un dato è stato letto/verificato. Prefisso
 *  scelto dal render (portale vs TreasureIQ), forma unica. */
export function Freschezza({
  prefisso,
  iso,
}: {
  prefisso: string;
  iso: string | null | undefined;
}) {
  if (!iso) return null;
  return (
    <p className="fonte-freschezza">
      {prefisso} {dataLeggibile(iso)}
    </p>
  );
}

/** Testo del chip: provenienza quando c'è, altrimenti ripiego sullo stato. */
function testoChip({
  origine,
  stato,
  lettoDalVivo,
  etichetta,
}: {
  origine?: "catalogo" | "live" | null;
  stato?: StatoFonte | null;
  lettoDalVivo?: boolean;
  etichetta?: string;
}): string {
  if (etichetta) return etichetta;
  if (origine === "catalogo") return "Catalogo nazionale";
  if (origine === "live") {
    return lettoDalVivo ? "Letto ora dal comune" : "Fonte del comune";
  }
  return ETICHETTA_CHIP_STATO[stato ?? "non_verificato"];
}

/**
 * Il chip di provenienza (colorato), più — quando c'è una provenienza vera —
 * lo stato come testo neutro, il chip d'accesso opzionale, e una nota
 * espandibile o statica.
 */
export function Provenienza({
  origine = null,
  stato = null,
  lettoDalVivo = false,
  accessMode = null,
  etichetta,
  nota,
}: {
  origine?: "catalogo" | "live" | null;
  stato?: StatoFonte | null;
  lettoDalVivo?: boolean;
  /** Solo rail informativo (origine null): il chip d'accesso, asse diverso
   *  dalla provenienza. Quando la provenienza c'è, la fonte parla da sé. */
  accessMode?: string | null;
  /** Etichetta esplicita del chip (ufficio/bandi, provenienza strutturale). */
  etichetta?: string;
  /** Caveat statico sotto il chip (es. bandi: «non un verdetto»). */
  nota?: string;
}) {
  // Nota espandibile a richiesta: solo sul «letto ora» interattivo del rail
  // servizio (nessuna etichetta esplicita, nessun caveat statico).
  const espandibile = lettoDalVivo && !etichetta && !nota;
  const [spiega, setSpiega] = useState(false);

  const testo = testoChip({ origine, stato, lettoDalVivo, etichetta });

  // C'è una provenienza vera quando il chip non è solo un ripiego sullo stato:
  // origine esplicita, oppure un'etichetta strutturale (ufficio/bandi live).
  const chipÈProvenienza = origine != null || etichetta != null;
  // Lo stato neutro accanto al chip si mostra solo se il chip è provenienza
  // (altrimenti lo stato È già il chip) e non è il caso «non disponibile».
  const mostraStato =
    chipÈProvenienza && stato != null && stato !== "unavailable";
  const accessChip =
    origine == null && accessLabel(accessMode) ? accessLabel(accessMode) : null;

  return (
    <p className="fonte-grammatica">
      {accessChip && (
        <span className="fonte-access" data-access-mode={accessMode ?? undefined}>
          {accessChip}
        </span>
      )}
      {espandibile ? (
        <span className="fonte-bollo-wrap">
          <button
            type="button"
            className="fonte-bollo fonte-bollo--vivo"
            data-origine={origine ?? undefined}
            data-stato={stato ?? undefined}
            aria-expanded={spiega}
            onClick={() => setSpiega((v) => !v)}
          >
            {testo}
          </button>
          {spiega && (
            <span className="fonte-nota" role="note">
              Dal portale del comune, in questo momento e alla lettera. Non è un
              dato che abbiamo verificato né conservato.
            </span>
          )}
        </span>
      ) : (
        <span
          className="fonte-bollo"
          data-origine={origine ?? undefined}
          data-stato={stato ?? undefined}
        >
          {testo}
        </span>
      )}
      {mostraStato && (
        <span className="fonte-stato" data-stato={stato ?? undefined}>
          · {ETICHETTA_STATO_NEUTRA[stato as Exclude<StatoFonte, "unavailable">]}
        </span>
      )}
      {nota && (
        <span className="fonte-nota fonte-nota--statica" role="note">
          {nota}
        </span>
      )}
    </p>
  );
}
