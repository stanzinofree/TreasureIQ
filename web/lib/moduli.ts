/** Canali esterni (D-S7). Nessuna PII passa da TreasureIQ: questi helper
 *  costruiscono link verso un canale già pubblico — la mail del Comune letta
 *  dal suo portale — non verso un form che raccoglie dati da noi. Il
 *  feedback sul progetto va al nostro store (D-01, ciclo 6): vedi
 *  `inviaFeedback` in `lib/api.ts` e il componente `Feedback.tsx`. */

/** Attributi fissi per ogni link verso un canale esterno, così ogni
 *  consumatore li applica identici (D-S7: `target=_blank rel=noopener`). */
export const LINK_ESTERNO = { target: "_blank", rel: "noopener" } as const;

/** Un indirizzo email è usabile in un `mailto:` solo se è davvero un indirizzo
 *  e nient'altro. I recapiti arrivano dallo scrape del portale comunale (D-S1):
 *  possono essere stringhe vuote, sporche, o contenere caratteri che nel mailto
 *  aprirebbero header aggiuntivi (a-capo, virgole, `?`). Regex volutamente
 *  stretta — nessuno spazio, nessun carattere di controllo, una sola `@` — e un
 *  tetto di lunghezza: un valore che non passa va trattato come «nessun recapito». */
const EMAIL_STRETTA = /^[^\s@,;:<>()"'?&%]+@[^\s@,;:<>()"'?&%]+\.[^\s@,;:<>()"'?&%]+$/;

export function emailValida(indirizzo: string | null | undefined): boolean {
  if (typeof indirizzo !== "string") return false;
  const pulito = indirizzo.trim();
  return pulito.length > 0 && pulito.length <= 254 && EMAIL_STRETTA.test(pulito);
}

/** Costruisce un href `mailto:` solo per un indirizzo che passa {@link emailValida},
 *  altrimenti null: chi chiama rende un semplice testo, non un link avvelenabile. */
export function mailtoSicuro(indirizzo: string | null | undefined): string | null {
  return emailValida(indirizzo) ? `mailto:${indirizzo!.trim()}` : null;
}

/** «Chiedi al tuo Comune di aprire i dati» → una mail precompilata al Comune,
 *  non a noi. Usa i recapiti già letti dal portale (D-S1): prima la mail
 *  ordinaria — un cittadino la scrive dal suo client — poi la PEC come ripiego.
 *  Restituisce null se il Comune non pubblica nessun recapito: senza un
 *  destinatario vero, un bottone che apre un mailto vuoto sarebbe disonesto,
 *  e chi chiama nasconde la sezione. */
export function linkAperturaDati(
  nomeComune: string,
  contatti: { email: string[]; pec: string[] } | null,
): string | null {
  // Primo recapito VALIDO (non il primo in lista): lo scrape può restituire
  // stringhe vuote o sporche prima di una mail buona. email ordinaria prima,
  // PEC come ripiego. Se nessuno passa emailValida → nessun destinatario onesto.
  const candidati = [...(contatti?.email ?? []), ...(contatti?.pec ?? [])];
  const destinatario = candidati.find(emailValida)?.trim() ?? null;
  if (destinatario === null) return null;

  const oggetto = `Pubblicazione dei requisiti delle agevolazioni — Comune di ${nomeComune}`;
  const corpo = [
    "Buongiorno,",
    "",
    `sul portale del Comune di ${nomeComune} diverse agevolazioni non riportano il campo «a chi spetta / requisiti»: la scheda del servizio esiste, ma quel campo è lasciato vuoto.`,
    "",
    "Chiedo, come cittadino, se sia possibile compilare e pubblicare i requisiti di accesso, così che chi cerca possa capire se ne ha diritto senza doverlo domandare allo sportello.",
    "",
    "Grazie.",
  ].join("\n");

  // encodeURIComponent (non URLSearchParams): nel mailto lo spazio va reso
  // come %20 e l'a-capo come %0A — i client di posta non decodificano il «+».
  const query = `subject=${encodeURIComponent(oggetto)}&body=${encodeURIComponent(corpo)}`;
  return `mailto:${destinatario}?${query}`;
}
