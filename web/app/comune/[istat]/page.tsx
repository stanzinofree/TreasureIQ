/**
 * Scheda-comune — quanto un comune ha davvero aperto il proprio portale.
 *
 * Server component, come `/dati`: la scheda è informazione pubblica su un
 * ente, non su una persona, quindi niente sessione da attendere. `force-dynamic`
 * perché il record arriva dallo store di scansione (B3/B5) e può cambiare a
 * ogni scan — una pagina statica mostrerebbe un «ultimo scan» vecchio.
 *
 * Titolo onesto: qui si parla di APERTURA del portale (D-S1/D-S2), mai di
 * «qualità del servizio» — l'aderenza AgID misura conformità, non giudica il
 * comune (RISK aderenza-scambiata-per-giudizio in spec.md).
 */

import { fetchSchedaComune, type SchedaComune } from "@/lib/api";
import { FORM_APERTURA_DATI_URL, LINK_ESTERNO } from "@/lib/moduli";

export const dynamic = "force-dynamic";

/** Data leggibile in it-IT, mai «Invalid Date» a schermo. Stesso formato di
 * `dataLeggibile` in Pannello.tsx — duplicato qui perché quella è privata al
 * suo modulo, non perché la forma debba divergere. */
function dataLeggibile(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/** Il blocco connettore: l'unico punto della scheda dove una % può comparire,
 * e solo per `connettore_tipo === "agid"` (D-S2). Ogni altro tier ha un
 * copy onesto, mai una cifra nuda. */
function BloccoConnettore({ scheda }: { scheda: SchedaComune }) {
  if (scheda.connettore_tipo === "agid" && scheda.aderenza) {
    const { percento, esposte, definite, superfici } = scheda.aderenza;
    return (
      <>
        <p className="scheda-comune__aderenza-cifra">
          Aderenza AgID <strong>{percento}%</strong>
          <span className="field__hint"> = {esposte}/{definite} superfici</span>
        </p>
        <ul className="scheda-comune__superfici">
          {superfici.map((s) => (
            <li key={s.nome} className="scheda-comune__superficie">
              <span>{s.nome}</span>
              <span className="scheda-comune__superficie-via">
                {s.via === "REST" ? "via REST" : s.via === "scrape" ? "via scrape" : "non raggiunta"}
              </span>
            </li>
          ))}
        </ul>
      </>
    );
  }
  if (scheda.connettore_tipo === "solo-html") {
    return <p className="lede">Solo HTML, dettaglio non ancora mappato.</p>;
  }
  return <p className="lede">Non ancora sondato.</p>;
}

export default async function SchedaComunePage({
  params,
}: {
  params: Promise<{ istat: string }>;
}) {
  const { istat } = await params;

  let scheda: SchedaComune | null = null;
  try {
    scheda = await fetchSchedaComune(istat);
  } catch {
    scheda = null;
  }

  if (!scheda) {
    return (
      <div className="panel">
        <h2>Comune non trovato</h2>
        <p className="lede">
          Non ho una scheda per il codice ISTAT {istat}. Verifica che l&apos;API
          sia in esecuzione e che il codice sia corretto, poi ricarica la
          pagina.
        </p>
      </div>
    );
  }

  return (
    <div className="stack">
      <section className="scheda-comune__testata">
        {scheda.logo_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={scheda.logo_url}
            alt=""
            className="scheda-comune__logo"
            loading="lazy"
            decoding="async"
          />
        )}
        <div>
          <p className="eyebrow">Apertura del portale</p>
          <h1>{scheda.nome}</h1>
          <p className="lede">
            Codice ISTAT {scheda.codice_istat}
            {scheda.sito && (
              <>
                {" "}
                ·{" "}
                <a href={scheda.sito} target="_blank" rel="noopener">
                  sito ufficiale
                </a>
              </>
            )}
          </p>
          <p className="field__hint">
            Ultimo scan: {dataLeggibile(scheda.scansionato_il)}
          </p>
        </div>
      </section>

      <section className="panel">
        <h2>Connettore</h2>
        <BloccoConnettore scheda={scheda} />
      </section>

      <section className="panel">
        <h2>Servizi esposti</h2>
        {scheda.servizi.esposto ? (
          <>
            <p className="lede">
              {scheda.servizi.totale} servizi via API.
            </p>
            {scheda.servizi.categorie.length > 0 && (
              <div className="scheda-comune__chip-riga">
                {scheda.servizi.categorie.map((cat) => (
                  <span key={cat.nome} className="scheda-comune__chip">
                    <span>{cat.nome}</span>
                    <span className="scheda-comune__chip-conteggio">
                      {cat.conteggio}
                    </span>
                  </span>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="lede">Nessuna API servizi esposta.</p>
        )}
        <p className="field__hint">
          Uffici via API: {scheda.uffici.esposto ? scheda.uffici.totale : "nessuno esposto"}
        </p>
      </section>

      <section className="panel">
        <h2>Contatti ufficiali</h2>
        {scheda.contatti &&
        (scheda.contatti.telefoni.length > 0 ||
          scheda.contatti.pec.length > 0 ||
          scheda.contatti.email.length > 0) ? (
          <>
            <dl className="scheda-comune__contatti">
              {scheda.contatti.telefoni.map((t) => (
                <div className="scheda-comune__contatti-riga" key={`tel-${t}`}>
                  <dt>Telefono</dt>
                  <dd>
                    <a href={`tel:${t.replace(/\s+/g, "")}`}>{t}</a>
                  </dd>
                </div>
              ))}
              {scheda.contatti.pec.map((p) => (
                <div className="scheda-comune__contatti-riga" key={`pec-${p}`}>
                  <dt>PEC</dt>
                  <dd>
                    <a href={`mailto:${p}`}>{p}</a>
                  </dd>
                </div>
              ))}
              {scheda.contatti.email.map((e) => (
                <div className="scheda-comune__contatti-riga" key={`mail-${e}`}>
                  <dt>Email</dt>
                  <dd>
                    <a href={`mailto:${e}`}>{e}</a>
                  </dd>
                </div>
              ))}
            </dl>
            <p className="field__hint">
              Letto via {scheda.contatti.fonte} il{" "}
              {dataLeggibile(scheda.contatti.letto_il)} · da verificare tu.
            </p>
          </>
        ) : (
          <p className="lede">Nessun contatto letto dalla scansione.</p>
        )}
      </section>

      {scheda.orari && scheda.orari.citazione && (
        <section className="panel">
          <h2>Orari uffici</h2>
          {scheda.orari.ufficio && (
            <p className="lede">{scheda.orari.ufficio}</p>
          )}
          <p className="scheda-comune__orari-citazione">
            &laquo;{scheda.orari.citazione}&raquo;
          </p>
          <p className="field__hint">
            Letto il {dataLeggibile(scheda.orari.letto_il)} · da verificare tu.
          </p>
        </section>
      )}

      <section className="panel">
        <h2>Vuoi che questo comune apra più dati?</h2>
        <p className="lede">
          Il modulo è esterno a TreasureIQ: nessun dato personale passa da noi.
        </p>
        <a
          className="button"
          href={FORM_APERTURA_DATI_URL}
          target={LINK_ESTERNO.target}
          rel={LINK_ESTERNO.rel}
        >
          Chiedi al tuo comune di aprire i dati
        </a>
      </section>
    </div>
  );
}
