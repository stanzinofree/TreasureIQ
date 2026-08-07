/** Moduli esterni (D-S7). Nessuna PII passa da TreasureIQ: i form vivono
 * fuori, su Google Forms, e queste costanti puntano solo lì. */

// Placeholder — da sostituire con URL reali (A4).
export const FORM_APERTURA_DATI_URL = "https://forms.gle/PLACEHOLDER-apertura-dati";
export const FORM_FEEDBACK_URL = "https://forms.gle/PLACEHOLDER-feedback";

/** Attributi fissi per ogni link verso un modulo esterno, così ogni
 * consumatore li applica identici (D-S7: `target=_blank rel=noopener`). */
export const LINK_ESTERNO = { target: "_blank", rel: "noopener" } as const;
