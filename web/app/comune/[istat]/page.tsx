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
import { linkAperturaDati, mailtoSicuro, LINK_ESTERNO } from "@/lib/moduli";

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

/** Iconcina per superficie AgID: un glifo per riconoscere a colpo d'occhio di
 * cosa parla la mini-card, senza emoji (design system). SVG 18px, stroke
 * `currentColor` così eredita il colore-stato dalla card. Mappa sulle quattro
 * superfici canoniche; qualunque nome fuori mappa cade su un pallino neutro. */
function IconaSuperficie({ nome }: { nome: string }) {
  const comune = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (nome) {
    case "servizi":
      return (
        <svg {...comune}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case "uffici":
      return (
        <svg {...comune}>
          <path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16" />
          <path d="M15 9h4a1 1 0 0 1 1 1v11" />
          <path d="M2 21h20M8 8h3M8 12h3M8 16h3" />
        </svg>
      );
    case "trasparenza":
      return (
        <svg {...comune}>
          <path d="M14 3v4a1 1 0 0 0 1 1h4" />
          <path d="M18 21H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h8l5 5v12a1 1 0 0 1-1 1z" />
          <path d="M9 13h6M9 17h6" />
        </svg>
      );
    case "contatti":
      return (
        <svg {...comune}>
          <path d="M4 4h16v13H7l-3 3z" />
          <path d="M8 9h8M8 12h5" />
        </svg>
      );
    default:
      return (
        <svg {...comune}>
          <circle cx="12" cy="12" r="4" />
        </svg>
      );
  }
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
          {superfici.map((s) => {
            const stato =
              s.via === "REST" ? "rest" : s.via === "scrape" ? "scrape" : "assente";
            return (
              <li
                key={s.nome}
                className={`scheda-comune__superficie scheda-comune__superficie--${stato}`}
              >
                <span className="scheda-comune__superficie-icona">
                  <IconaSuperficie nome={s.nome} />
                </span>
                <span className="scheda-comune__superficie-nome">{s.nome}</span>
                <span className="scheda-comune__superficie-via">
                  {s.via === "REST"
                    ? "via REST"
                    : s.via === "scrape"
                      ? "via scrape"
                      : "non raggiunta"}
                </span>
              </li>
            );
          })}
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
    <div className="stack scheda-comune">
      <section className="scheda-comune__testata">
        {scheda.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={scheda.logo_url}
            alt=""
            className="scheda-comune__logo"
            loading="lazy"
            decoding="async"
          />
        ) : (
          // Nessun logo letto dal portale (comune solo-HTML, o stemma non
          // esposto). Invece del vuoto, un monogramma: la testata ha sempre un
          // segno grafico, e non fingiamo uno stemma che non abbiamo.
          <span className="scheda-comune__logo scheda-comune__logo--mono" aria-hidden>
            {scheda.nome.trim().charAt(0).toUpperCase()}
          </span>
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
                    {mailtoSicuro(p) ? <a href={mailtoSicuro(p)!}>{p}</a> : p}
                  </dd>
                </div>
              ))}
              {scheda.contatti.email.map((e) => (
                <div className="scheda-comune__contatti-riga" key={`mail-${e}`}>
                  <dt>Email</dt>
                  <dd>
                    {mailtoSicuro(e) ? <a href={mailtoSicuro(e)!}>{e}</a> : e}
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

      {(() => {
        // Precompila la mail verso i recapiti veri del Comune; null se non ne
        // pubblica nessuno — allora la sezione sparisce invece di offrire un
        // bottone che non porta da nessuna parte.
        const mailtoApertura = linkAperturaDati(scheda.nome, scheda.contatti);
        if (mailtoApertura === null) return null;
        return (
          <section className="panel">
            <h2>Vuoi che questo comune apra più dati?</h2>
            <p className="lede">
              Apre una mail già scritta verso il Comune di {scheda.nome}: la
              mandi tu, dal tuo client. Nessun dato personale passa da TreasureIQ.
            </p>
            <a
              className="button scheda-comune__apri"
              href={mailtoApertura}
              target={LINK_ESTERNO.target}
              rel={LINK_ESTERNO.rel}
            >
              Chiedi al tuo comune di aprire i dati
            </a>
          </section>
        );
      })()}
    </div>
  );
}
