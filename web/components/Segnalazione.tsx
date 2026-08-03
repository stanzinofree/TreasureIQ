"use client";

/**
 * B22 (D-25) — a citizen-generated request to open a comune's data, never a
 * sent one. Three separate, explicit actions: generate the text, open the
 * citizen's own email client, copy the text to the clipboard. Nothing here
 * transmits anything on its own — no server-side mail delivery of any kind,
 * no outbound request beyond the anonymous counter increment
 * (`POST /api/segnalazioni`, which carries the ISTAT code and nothing else).
 *
 * Why generate and not send (`.kapi/spec.md` D-25): a send button that
 * quietly logged this to a file would be the single most damaging thing in
 * a project whose entire claim is honesty about data.
 */

import { useEffect, useState } from "react";
import { inviaSegnalazione, segnalazioni, type InfoOffice } from "@/lib/api";

/** D-26's comparative benchmark: `calendario raccolta differenziata` on
 * dati.gov.it CKAN returned 342 results, measured 2026-08-02 (F-1 in
 * `.kapi/spec.md`). A static, dated fact composed here — never through the
 * model — exactly like `integration.cost_lines` composes its own D-24
 * sentences server-side. */
const BENCHMARK_LINE =
  "a differenza di quanto gia' avviene in almeno 342 Comuni italiani, dove ad esempio il " +
  "calendario della raccolta differenziata e' pubblicato come open data su dati.gov.it " +
  "(dato misurato il 2026-08-02).";

function isPlausibleEmail(value: string): boolean {
  return /^[^\s<>"']+@[^\s<>"']+\.[^\s<>"']+$/.test(value);
}

/** D-26 rule 3: every sentence here states a fact about what the portal
 * publishes, never a judgement about the comune or the people who run it.
 * D-26 rule 2: the cost named is TreasureIQ's integration cost, never the
 * citizen's — nothing below asks the citizen for anything but a name. */
function buildRequest(ente: string): { subject: string; body: string } {
  const subject = `Richiesta di pubblicazione in formato open data — ${ente}`;
  const body = [
    "Gentile Ufficio,",
    "",
    "sto usando TreasureIQ, uno strumento che confronta i dati pubblicati online dai Comuni " +
      "per aiutare i cittadini a trovare bandi, agevolazioni e informazioni di servizio.",
    "",
    `Il portale online del ${ente} non pubblica questi dati in un formato aperto e ` +
      `interrogabile (open data / API): oggi la stessa informazione non e' raggiungibile ` +
      `con un'unica richiesta automatica, ${BENCHMARK_LINE}`,
    "",
    "Chiedo che l'ente valuti la pubblicazione di questi dati in un formato aperto, secondo " +
      "le indicazioni tecniche di AGID (https://www.agid.gov.it/it/ambiti-intervento/open-data) " +
      "e gli standard del Catalogo nazionale degli schemi (https://www.schema.gov.it/), " +
      "rendendoli reperibili anche su dati.gov.it (https://www.dati.gov.it/).",
    "",
    "Grazie per l'attenzione.",
  ].join("\n");
  return { subject, body };
}

export default function Segnalazione({
  codiceIstat,
  ente,
  office,
}: {
  codiceIstat: string;
  ente: string;
  office: InfoOffice | null;
}) {
  const [count, setCount] = useState<number | null>(null);
  const [generated, setGenerated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyNote, setCopyNote] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    segnalazioni()
      .then((data) => live && setCount(data[codiceIstat] ?? 0))
      .catch(() => {
        // Silent: the counter is a nice-to-have caption, not load-bearing.
      });
    return () => {
      live = false;
    };
  }, [codiceIstat]);

  const { subject, body } = buildRequest(ente);
  const recipient = office?.email && isPlausibleEmail(office.email) ? office.email : "";
  const mailtoHref = `mailto:${recipient}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const updated = await inviaSegnalazione(codiceIstat);
      setCount(updated[codiceIstat] ?? null);
      setGenerated(true);
    } catch {
      setError(
        "Non riesco a raggiungere il servizio. Verifica che l'API sia in esecuzione su localhost:8010.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function copyToClipboard() {
    const text = `${subject}\n\n${body}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopyNote("Testo copiato negli appunti.");
    } catch {
      setCopyNote("Non riesco a copiare automaticamente: seleziona e copia il testo qui sotto.");
    }
  }

  return (
    <div className="panel" style={{ marginTop: "var(--ma-4)" }}>
      <h3 style={{ fontSize: "1rem" }}>Chiedi al Comune di aprire questi dati</h3>
      <p style={{ fontSize: "0.9rem", color: "var(--sumi-soft)" }}>
        TreasureIQ pu&ograve; preparare una richiesta di pubblicazione in formato open data. Non
        la invia: la genera, e sei tu a inviarla.
      </p>

      {count != null && (
        <p
          style={{
            fontSize: "0.85rem",
            fontFamily: "var(--font-mono)",
            color: "var(--sumi-faint)",
          }}
        >
          {count === 0
            ? "Nessun cittadino ha ancora generato questa richiesta per questo Comune."
            : `${count} ${count === 1 ? "cittadino ha" : "cittadini hanno"} chiesto a questo Comune di aprire questi dati.`}
        </p>
      )}

      {!generated && (
        <button type="button" className="button" onClick={generate} disabled={busy}>
          {busy ? "Genero la richiesta…" : "Genera la richiesta"}
        </button>
      )}

      {error && (
        <p className="notice" role="alert" style={{ marginTop: "var(--ma-2)" }}>
          {error}
        </p>
      )}

      {generated && (
        <div style={{ marginTop: "var(--ma-3)" }}>
          <p style={{ fontSize: "0.85rem" }}>
            <strong>Questa richiesta non &egrave; stata inviata.</strong> Sei tu a inviarla: apri
            il tuo client email o copiala. In produzione il sistema potrebbe inoltrarla
            direttamente al Comune.
          </p>

          <pre
            style={{
              whiteSpace: "pre-wrap",
              fontFamily: "var(--font-mono)",
              fontSize: "0.78rem",
              background: "var(--paper-sunken)",
              padding: "var(--ma-3)",
              marginTop: "var(--ma-2)",
            }}
          >
            {`${subject}\n\n${body}`}
          </pre>

          <div className="grid-2" style={{ marginTop: "var(--ma-2)" }}>
            <a className="button" href={mailtoHref}>
              Apri client email
            </a>
            <button type="button" className="button" onClick={copyToClipboard}>
              Copia il testo
            </button>
          </div>

          {copyNote && (
            <p style={{ fontSize: "0.8rem", color: "var(--sumi-faint)", marginTop: "var(--ma-2)" }}>
              {copyNote}
            </p>
          )}

          {!recipient && (
            <p style={{ fontSize: "0.8rem", color: "var(--sumi-faint)", marginTop: "var(--ma-2)" }}>
              Il Comune non pubblica un indirizzo email per questo ufficio: inserisci tu il
              destinatario nel client email.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
