/** Canali esterni (D-S7). Nessuna PII passa da TreasureIQ: questi helper
 *  costruiscono link verso canali già pubblici — GitHub, o la mail del Comune
 *  letta dal suo portale — non verso un form che raccoglie dati da noi. */

const REPO = "https://github.com/stanzinofree/TreasureIQ";

/** Attributi fissi per ogni link verso un canale esterno, così ogni
 *  consumatore li applica identici (D-S7: `target=_blank rel=noopener`). */
export const LINK_ESTERNO = { target: "_blank", rel: "noopener" } as const;

/** Feedback sul progetto → una issue su GitHub, il canale reale di chi lo
 *  mantiene. Niente Google Form e niente dati raccolti da noi: chi scrive lo
 *  fa su GitHub, con la propria identità, in pubblico. La label preseleziona
 *  la corsia giusta; il titolo è solo un segnaposto che l'utente riscrive. */
export function linkFeedback(): string {
  const params = new URLSearchParams({
    labels: "feedback",
    title: "Feedback dal cittadino",
  });
  return `${REPO}/issues/new?${params.toString()}`;
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
  const destinatario = contatti?.email[0] ?? contatti?.pec[0] ?? null;
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
