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

import {
  catalogAccessFor,
  fetchRegistroComune,
  fetchSchedaComune,
  type CatalogAccess,
  type RegistroComune,
  type SchedaComune,
} from "@/lib/api";
import { linkAperturaDati, mailtoSicuro, LINK_ESTERNO } from "@/lib/moduli";
import { nome } from "@/lib/palette";

export const dynamic = "force-dynamic";

/** Valori di `piattaforma_at` che NON sono un vendor: la sonda ha guardato ma
 *  non ha trovato/riconosciuto un portale trasparenza. Copertura onesta, non
 *  un nome da mostrare come se fosse un prodotto. */
const AT_NON_VENDOR = new Set(["non_trovata", "ignota", "non_misurata", ""]);

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

/** La famiglia piattaforma riconosciuta dal censimento nazionale. Vive sopra al
 *  tier del connettore perché è indipendente da esso: un comune peopleweb resta
 *  peopleweb anche se il portale non espone REST AgID e il tier cade su
 *  "solo-html". `null` quando il comune non è ancora nel censimento. */
function BloccoPiattaforma({ scheda }: { scheda: SchedaComune }) {
  if (!scheda.piattaforma) return null;
  const atVendor =
    scheda.piattaforma_at && !AT_NON_VENDOR.has(scheda.piattaforma_at)
      ? scheda.piattaforma_at
      : null;
  return (
    <dl className="scheda-comune__piattaforma">
      <div>
        <dt>Piattaforma portale</dt>
        <dd>{nome(scheda.piattaforma)}</dd>
      </div>
      <div>
        <dt>Amministrazione trasparente</dt>
        <dd>
          {atVendor ? nome(atVendor) : "portale non individuato"}
          {scheda.at_url ? (
            <>
              {" — "}
              <a href={scheda.at_url} target="_blank" rel="noreferrer">
                apri
              </a>
            </>
          ) : null}
        </dd>
      </div>
      {scheda.classificato_da ? (
        <div>
          <dt>Riconosciuta da</dt>
          <dd>
            {scheda.classificato_da === "sonda"
              ? "sonda automatica"
              : scheda.classificato_da}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

/** Il blocco connettore: l'unico punto della scheda dove una % può comparire,
 * e solo per `connettore_tipo === "agid"` (D-S2). Ogni altro tier ha un
 * copy onesto, mai una cifra nuda. La famiglia piattaforma (BloccoPiattaforma)
 * la precede in ogni tier: è il "cosa" del portale, il tier è il "come" lo
 * leggiamo. */
function BloccoConnettore({ scheda }: { scheda: SchedaComune }) {
  const piattaforma = <BloccoPiattaforma scheda={scheda} />;
  if (scheda.connettore_tipo === "agid" && scheda.aderenza) {
    const { percento, esposte, definite, superfici } = scheda.aderenza;
    return (
      <>
        {piattaforma}
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
    return (
      <>
        {piattaforma}
        <p className="lede">
          {scheda.piattaforma
            ? "Il portale non espone i cataloghi REST AgID: le superfici si leggono via scraping HTML."
            : "Solo HTML, dettaglio non ancora mappato."}
        </p>
      </>
    );
  }
  return (
    <>
      {piattaforma}
      <p className="lede">Non ancora sondato.</p>
    </>
  );
}

const SURFACE_LABEL: Record<CatalogAccess["surface"], string> = {
  ordinary_data: "Dati ordinari",
  transparency: "Amministrazione Trasparente",
};

const ACCESS_LABEL: Record<CatalogAccess["access_mode"], string> = {
  direct: "Dato diretto",
  mediated: "Dato mediato",
  indirect: "Dato indiretto",
  unavailable: "Fonte non disponibile",
};

const COMPATIBILITY_LABEL: Record<string, string> = {
  compatible: "compatibilità AGID completa",
  partial: "compatibilità AGID parziale",
  incompatible: "non compatibile con AGID",
  unknown: "compatibilità AGID non misurata",
};

function CatalogAccessPanel({ entries }: { entries: CatalogAccess[] }) {
  if (entries.length === 0) return null;
  return (
    <section className="panel">
      <h2>Come si raggiungono i dati</h2>
      <p className="nota">
        La misura distingue il portale dei dati ordinari da quello di
        Amministrazione Trasparente. Non è un giudizio sul comune: indica solo
        quanto il dato è immediato da leggere.
      </p>
      <dl className="scheda-comune__piattaforma">
        {entries.map((entry) => (
          <div key={entry.surface}>
            <dt>{SURFACE_LABEL[entry.surface]}</dt>
            <dd>
              <strong>{ACCESS_LABEL[entry.access_mode]}</strong>
              <br />
              <span className="field__hint">
                {entry.platform_id ?? "piattaforma non individuata"} ·{" "}
                {COMPATIBILITY_LABEL[entry.platform_compatibility] ??
                  entry.platform_compatibility}
                <br />
                misurato il {dataLeggibile(entry.measured_at)}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
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

  let registro: RegistroComune | null = null;
  try {
    registro = await fetchRegistroComune(istat);
  } catch {
    registro = null;
  }

  let accessEntries: CatalogAccess[] = [];
  try {
    accessEntries = await catalogAccessFor(istat);
  } catch {
    accessEntries = [];
  }

  if (!scheda) {
    return (
      <div className="panel">
        <h2>Comune non trovato</h2>
        <p className="lede">
          Non ho una scheda per questo comune. Verifica che l&apos;API sia in
          esecuzione e che l&apos;indirizzo sia corretto, poi ricarica la
          pagina.
        </p>
      </div>
    );
  }

  return (
    <div className="stack scheda-comune">
      <section className="scheda-comune__testata">
        {registro?.logo_b64 ? (
          // Logo curato dal registro (CONTRATTO-O2, D-11): arriva già come
          // base64 dalla scansione, nessuna fetch da qui verso il portale.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={registro.logo_b64}
            alt={`Logo del Comune di ${scheda.nome}`}
            className="scheda-comune__logo"
          />
        ) : scheda.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={scheda.logo_url}
            alt={`Logo del Comune di ${scheda.nome}`}
            className="scheda-comune__logo"
            loading="lazy"
            decoding="async"
          />
        ) : (
          // Nessun logo né dal registro né dal portale (comune solo-HTML, o
          // stemma non esposto). Invece del vuoto, un monogramma civico
          // neutro: la testata ha sempre un segno grafico, mai uno stemma
          // finto (D-02).
          <span className="scheda-comune__logo scheda-comune__logo--mono" aria-hidden>
            {scheda.nome.trim().charAt(0).toUpperCase()}
          </span>
        )}
        <div>
          <p className="eyebrow">Apertura del portale</p>
          <h1>{scheda.nome}</h1>
          {scheda.sito && (
            <p className="lede">
              <a
                href={
                  scheda.sito.startsWith("http")
                    ? scheda.sito
                    : `https://${scheda.sito}`
                }
                target="_blank"
                rel="noopener"
              >
                sito ufficiale
              </a>
            </p>
          )}
          <p className="field__hint">
            Ultimo scan: {dataLeggibile(scheda.scansionato_il)}
          </p>
          {registro &&
            (registro.prima_scansione ? (
              <p className="card-comune__nota">
                Prima scansione, niente da confrontare.
              </p>
            ) : (
              registro.cambiato && (
                <p className="card-comune__nota card-comune__nota--cambiato">
                  Cambiato dall&apos;ultima scansione: {registro.cambiato.campi.join(", ")}.
                </p>
              )
            ))}
        </div>
      </section>

      {accessEntries.length > 0 ? (
        <CatalogAccessPanel entries={accessEntries} />
      ) : (
        <section className="panel">
          <h2>Misura del portale</h2>
          <BloccoConnettore scheda={scheda} />
        </section>
      )}

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
        ) : registro?.uffici_snapshot?.length ? (
          <>
            <p className="lede">
              {registro.uffici_snapshot.length} servizi rilevati dal portale
              (lettura HTML, non via API AgID).
            </p>
            <div className="scheda-comune__chip-riga">
              {registro.uffici_snapshot.map((u) => (
                <span key={u.nome} className="scheda-comune__chip">
                  <span>{u.nome}</span>
                </span>
              ))}
            </div>
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
