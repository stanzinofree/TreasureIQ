// Etichetta umana per l'`access_mode` di una fonte. Condivisa da due punti che
// devono nominare la stessa modalita' allo stesso modo:
//  - SourceAccessBadge (chip standalone, rami non-informazione);
//  - RispostaCivica (riga di provenienza in coda alla card informazione).
// Sta in un modulo a se' per non creare una dipendenza circolare fra i due
// componenti (Chat.tsx importa RispostaCivica, non viceversa).
export function accessLabel(
  accessMode: string | null | undefined,
): string | null {
  if (!accessMode) return null;
  const etichette: Record<string, string> = {
    direct: "Dato diretto",
    mediated: "Dato mediato",
    indirect: "Dato da verificare",
    unavailable: "Fonte non disponibile",
    M2_prosa_api: "Dato mediato",
    M4_connettore: "Dato mediato",
    M5_nessuno: "Dato da verificare",
    M6_web_aperto: "Dato da verificare",
  };
  return etichette[accessMode] ?? "Fonte verificata";
}
