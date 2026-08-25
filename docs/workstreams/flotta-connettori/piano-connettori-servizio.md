# Piano sviluppo — estensione flotta connettori-servizio

_Rev 2, 2026-08-25. Incorpora la review Codex. **Non è ancora un piano esecutivo**: è un piano di **ricognizione**. Nessun target sotto è autorizzato all'implementazione finché la sua scheda recon non esiste ed è verde._

## 0. Premesse ferme (non ridiscutere)

- **Due layer distinti**:
  - **Riconoscimento / flotta base** — firma piattaforma → uffici, aree, AT. Dispatch `connettore.py:leggi_connettore` su `firma.piattaforma`.
  - **Catalogo servizio** — `ServiceKey` → `ServiceReference`. È il layer del catalogo nazionale.
- **Connettori-servizio operativi oggi: 2** (verificati in codice):
  - `catalog/service_connectors/wordpress_agid.py` → `WordPressAgidServiceConnector`
  - `catalog/service_connectors/comweb_service.py` → `ComWebServiceConnector`
  - ⚠️ `catalog/wordpress_connector.py` è **un altro** connettore (layer base/flotta), **non** il service connector. Non confonderli.
- **La selezione connettore NON è un `if piatt == …`.** Il runtime usa `default_service_registry(esecutore)` (`catalog/service_registry.py:49`) che popola un `ConnectorRegistry` con `reg.register(...)`, risolto da `ConnectorRegistry.resolve()` (`catalog/connector_registry.py`). Il branch `if piatt=='comweb' … else Wp` nei runner di fan-out (`scratchpad/fanout_nazionale.py`, `live_resolve.py`) è una **scorciatoia operativa dello sweep**, non il contratto architetturale. **Un nuovo connettore si registra nel registry**, non si aggiunge un secondo dispatcher parallelo.
- **Ogni nuovo connettore riusa**: resolver, `service_cache`, `EsecutoreServiceFetcher` guardato (host-guard + rate-limit/budget), contratto `ServiceReference`.
- **Regola d'oro**: "riconoscimento + mappa presenti" **≠** "service connector facile". La priorità dipende dalla **superficie servizio realmente interrogabile per-ServiceKey**, non dal riconoscimento della piattaforma.

## 1. Fotografia piattaforme — DATO SEPARATO, non stima di copertura

> ⚠️ I numeri qui sotto vengono da una query diversa dal pool di sweep. **Non usarli per stimare la copertura del catalogo servizi.**
>
> **Fonte**: `data/storico.db`, tabella `portale_snapshot`, ultimo rilievo per comune (`ROW_NUMBER() … PARTITION BY codice_istat ORDER BY rilevato_il DESC`), GROUP BY `piattaforma`. Rilevato 2026-08-25. 7896 comuni distinti.

| Piattaforma | Comuni (snapshot) | Riconoscimento | Service connector |
|---|---:|---|---|
| peopleweb (openweb+siscom) | 1120 | ✅ | ❌ |
| municipium | 1010 | ✅ | ❌ |
| hgate / eGov (Halley) | 956 | ✅ `egov.py` | ❌ |
| wordpress_generico | 727 | ✅ | ✅ (pool sweep) |
| wp_design_comuni | 713 | ✅ | ✅ (pool sweep) |
| comweb (ePublic) | 503 | ✅ | ✅ (pool sweep) |
| openpa (Maggioli) | 363 | ✅ `openpa.py` | ❌ |
| agenda_smart | 377 | ❌ | ❌ |
| magnolia | 171 | ❌ | ❌ |
| drupal | 154 | ❌ | ❌ |
| comunibootstrapitalia | 50 | via wp_agid | ⚠️ da provare |
| regionali (fvg/veneto/lepida) | 168/85/70 | ❌ | ❌ |
| plone/pageobject/joomla/dotnetnuke | ≤68 | parziale/❌ | ❌ |
| **ignota** 844 / **non_misurata** 291 | — | — | non connettibili |

**Pool del service sweep nazionale (dato autorevole, distinto dalla tabella sopra):**
`713 wp_design_comuni + 727 wordpress_generico + 503 comweb = 1943`.

## 2. Roadmap — priorità di RICOGNIZIONE (non di implementazione)

| Ordine | Target | Azione | Stato evidenza |
|---|---|---|---|
| **0** | baseline attuale | chiudere live-resolve + promozione del catalogo esistente | ✅ fatto — PR #28 (1244 comuni, 3402 reference) |
| **1** | comunibootstrapitalia | recon breve: compatibile WP/AgID o dialetto proprio? | ✅ spike fatto (2026-08-25) → **dialetto proprio OpenWeb, NON WP/AgID**; vedi scheda §3-bis. Converge su order 3 (PeopleWeb-OpenWeb) |
| **2** | OpenPA | recon REST + fixture; candidato al **primo nuovo adapter reale** | pista REST concreta, da validare |
| **3** | PeopleWeb / OpenWeb | **separare** i due vendor (OpenWeb vs Siscom), poi scegliere il più esposto; comunibootstrapitalia rientra qui (stesso dialetto OpenWeb) | 2 dialetti, non 1 connettore |
| **4** | Hgate / Halley | verificare portale `/zf`, URL, access mode | recon dedicata prima |
| **5** | Municipium | **solo se** emerge una superficie per-servizio | ⛔ oggi SPA/API WAF-bloccata, nessuna superficie HTML per-ServiceKey → **honest miss documentato** finché l'evidenza non cambia |

**Cambio chiave rispetto alla rev 1**: peopleweb/municipium/hgate **non** sono P1 di implementazione. Avere riconoscimento+mappa non basta. In particolare **Municipium non è il prossimo connettore** finché non cambia l'evidenza tecnica.

## 3. Scheda recon obbligatoria per ogni target (gate prima di implementare)

Ogni target passa da questa scheda **verde** prima di scrivere il connettore:

1. **platform ID esatto** (come appare in `firma.piattaforma`).
2. **URL / superficie interrogabile** per-ServiceKey (endpoint reale, non home).
3. **ServiceKey dimostrabili** — quali delle 6 (carta_identita, cambio_residenza, accesso_atti, stato_civile, tributi_imu, tributi_tari) hanno una superficie reale.
4. **forma dei candidati** (REST/HTML, shape del payload).
5. **evidenza URL** (source_url + ≥1 opzione con url → `ServiceReference` completa).
6. **access mode** (diretto vs ricerca web; gate su M5 dipendente dal connettore).
7. **numero di richieste** per (istat,key) — budget realistico.
8. **casi vuoto / ambiguo** — come si comporta.
9. **eventuali dialetti** (es. peopleweb 2 vendor).
10. **decisione**: connettibile **oppure** honest miss documentato.

## 3-bis. Scheda recon COMPILATA — comunibootstrapitalia (spike order 1, 2026-08-25)

Sonda live read-only su 3 comuni (Castro `016065`, Bianzano `016026`, Predore) + census `portale_snapshot`.

1. **platform ID**: `comunibootstrapitalia` (50 comuni snapshot). Home: nginx, tema `bootstrap-italia`, `rotte=php`.
2. **superficie per-ServiceKey**: schede servizio `/scheda-ist/<slug>` (HTML, family-wide: presenti su tutti e 3 i comuni). Portale autenticato OpenWeb su host separato `servizi.<comune>/openweb/` + `/portal/autenticazione/`. AT su `/Pages/amministrazione_trasparente_v3_0/?code=AT.*` (codificata).
3. **ServiceKey dimostrabili**: da confermare per-key; le schede esistono ma **non c'è indice/REST**: `/scheda-ist/` nudo → 404, gli slug sono diretti. Discovery per-key richiede una pagina di ricerca/indice, non una GET secca.
4. **forma candidati**: **HTML** (no REST). `/wp-json/` → **404 su tutti e 3** (prova che NON è WordPress). `/api/` → 404.
5. **evidenza URL**: scheda `/scheda-ist/<slug>` = source_url plausibile; opzione autenticata = portale `servizi.<host>/openweb/`. Da verificare che la scheda porti ≥1 link accesso (come per comweb via `service_page`).
6. **access mode**: misto — informazione (scheda HTML) + autenticato (portale OpenWeb, host separato → attenzione host-guard cross-host).
7. **budget**: ignoto finché non si trova il meccanismo di discovery per-key (probabile: 1 fetch indice + 1 scheda).
8. **casi vuoto/ambiguo**: `/Pages/` → 302 `/Error/404`; slug errato → 404. Miss onesto pulito.
9. **dialetto**: **OpenWeb** (marker `soluzionipa`/`openweb` su Castro). Stesso vendor di PeopleWeb-OpenWeb ([[peopleweb-due-vendor-openweb-siscom]]) → **non un connettore a sé**, va unificato con order 3.
10. **DECISIONE**: **NON riducibile al `WordPressAgidServiceConnector`** (nessuna REST wp/v2, provato). È il dialetto OpenWeb, superficie HTML `/scheda-ist/`. **Non è il primo nuovo adapter**: rientra nella recon OpenWeb (order 3). Nessuna implementazione ora; il prossimo adapter reale resta **OpenPA (order 2)** dopo la sua recon.

## 3-ter. Scheda recon COMPILATA — OpenPA (spike order 2, 2026-08-25)

Sonda live read-only su 2 comuni: **Storo** `022183` (`www.comune.storo.tn.it`) e **Lodrino** BS (`www.comune.lodrino.bs.it`) + fixture `api/tests/fixtures/openpa_storo_*.html` + v0 `treasureiq/openpa.py`. Superficie **per-ServiceKey** (nuova); la BASE (uffici/AT) è già coperta da `leggi_openpa`.

1. **platform ID**: `openpa` (come `platform_id` in `catalog/flotta/openpa/base.py`; firma via `ingest.piattaforma._DA_IMPRONTA`). Vendor reale = **OpenCity Labs su eZ Publish**: extension `openpa_bootstrapitalia`, asset `static.opencityitalia.it`, footer `opencitylabs.it` — non Plone, non Maggioli. ~363 comuni (§1).
2. **superficie per-ServiceKey**: catalogo UI `/Servizi` → 7 categorie AGID fisse `/Servizi/(view)/{Categoria}`. **Trappola**: le voci servizio sono renderizzate **client-side** (template JsRender `{{if}}`/`{{:}}`) → un fetch statico (quello che fa il connettore, senza JS) vede **gusci vuoti**. Il layer machine-readable è **OpenData REST**: prefisso **`/opendata/api/`** (NON `/api/`) → `content/search/?q=<query>`, `classes/`, `tags_tree/`, `geo/search/`. Scoperto in modo deterministico dal bundle JS cached `/var/{instance}/cache/public/javascript/*.js`, non per tentativi.
3. **ServiceKey dimostrabili**: **nessuna ancora provata per-key.** `content/search` è vivo e interroga (risponde JSON strutturato), ma `q` è **DSL eZ Find** (Solr-like), non testo libero: token nudo → `"first token is not a field nor parameter"`; `and classes [servizio]` → `"Class servizio not found"` (identifier di classe reale ignoto; `/opendata/api/classes/` = **500** su Storo). Le 6 chiavi non sono dimostrabili finché non si hanno grammatica + class-id.
4. **forma candidati**: **REST JSON** (OpenData eZ Find) — errori tipizzati `{"error_code","error_message"}` ⇒ contratto stabile; una risposta *hit* non è ancora stata ottenuta (query non valida). Il catalogo HTML è JS-rendered ⇒ inservibile a fetch statico. Endpoint Plone-style **chiusi**: `/++api++` 404, `/@@search` e `/RSS` **410 Gone**.
5. **evidenza URL**: la scheda servizio (risolta via REST o via nodo) darà `source_url`; ma la **consegna è spesso delegata off-portal**: link `form.agid.gov.it/view/{uuid}` dentro le categorie + SPA "Stanza del cittadino" sul subdomain `servizi.<comune>` (il root `servizi.` fa 302 → `www/Servizi`). Un `ServiceReference` completo dipende dal punto 3.
6. **access mode**: **misto** — REST OpenData (diretto, se si dominano query+class) vs delega esterna (AGID forms / SPA autenticata, host separato → host-guard cross-host). Gate M5 dipende dall'esito REST.
7. **budget**: stimato 1 fetch `/opendata/api/content/search` per (istat,key) **se** la query per-key è deterministica, + 1 fetch una-tantum `classes`/`tags_tree` per gli identifier. Non stimabile davvero prima del punto 3.
8. **casi vuoto/ambiguo**: REST → 400 JSON esplicito (`"Empty string"`, `"Inconsistent query"`, `"Class X not found"`) — miss diagnosticabile e pulito. Categoria HTML inesistente → gestita server-side.
9. **dialetti / sovrapposizione**: vendor unico OpenCity Labs/eZ. **Stesso ceppo di comunibootstrapitalia (order 1)**: entrambi bootstrap-italia su CDN `opencityitalia`. Da verificare se comunibootstrapitalia espone lo stesso `/opendata/api/` — **potrebbero essere lo stesso adapter**, non due. Cfr. [[comunibootstrapitalia-e-openweb]], §3-bis.
10. **DECISIONE**: la pista **OpenData REST è concreta e viva** (endpoint confermato su **2 comuni**: stesso stack `opencityitalia`, stessa semantica d'errore) **ma la scheda NON è ancora verde**: manca la grammatica `q` per-ServiceKey e gli identifier di classe; il catalogo HTML non è una GET secca. ⇒ **Nessuna implementazione ora.** Prossimi passi recon (read-only): (a) ottenere una risposta *hit* valida da `content/search` con la DSL eZ Find corretta + un class-id reale (leggere il bundle JS per il query-builder, o `tags_tree`); (b) mappare le 6 ServiceKey a query deterministiche; (c) sciogliere la sovrapposizione con order 1; (d) allargare il campione a un comune OpenPA grande (Storo/Lodrino sono istanze PNRR piccole). Solo allora OpenPA diventa il primo nuovo adapter.

## 4. Punti di sincronizzazione a ogni nuovo connettore-servizio

> ⚠️ Riferimenti da ispezione codice 2026-08-25 + memory. Verificare file:line prima di dare per fatto.

1. **Registrazione nel registry** — `reg.register(NuovoServiceConnector(transport.con(_NuovaDiscovery())))` dentro `default_service_registry()` (`catalog/service_registry.py:49-62`). **Non** un dispatcher parallelo.
2. **Nuova classe** in `catalog/service_connectors/`, sottoclasse `_ServiceConnectorBase` (`connettore_base.py`); modello: `comweb_service.py` / `wordpress_agid.py`.
3. **Strategia discovery** per famiglia (`_WpDiscovery`/`_ComWebDiscovery` in `esecutore_fetcher.py` / `comweb_service.py`) — aggiungere la propria.
4. **Contratto D-09** (mappa_connettore → ServiceReference): confine diretto-vs-web (contatti/bandi restano scrape), forma REST AgID.
5. **`service_cache`** (`catalog/service_cache.py`): reference completa (service_id ∧ title ∧ source_url ∧ ≥1 opzione con url) → salva; incompleta → skip, mai fetch implicito.
6. **Trasversali**: host-guard/SSRF a 0, logo per-piattaforma (CDN vendor → same-host stretto può degradare a None, è di piattaforma), aderenza AT onesta, `storico.db` read-only.

_Se il target tocca anche il layer riconoscimento (piattaforma non ancora riconosciuta): dispatch `connettore.py:leggi_connettore`, `_LEGGIBILI` in `registro_cli.py`, `LEGGIBILI` in `web/app/analytics/page.tsx` (+ prosa), `_estrattori_logo_portale()` in `registro.py`._

## 5. Note tecniche per Codex (da verificare, non assumere)

- **peopleweb** = due vendor discriminati dall'HTML home (`_e_openweb`): OpenWeb/SoluzioniPA vs Siscom/ASP.NET. Servono probabilmente **due** connettori o uno con branch esplicito. Cfr. memory [[peopleweb-due-vendor-openweb-siscom]].
- **hgate/Halley**: servizi/modulistica spesso nel portale `/zf` separato. Cfr. [[portale-halley-zf-scoperto]].
- **municipium**: dominio proprio via `/it/sitemap`, per-ufficio spesso non pubblicato; verificato SPA/API dietro WAF. Cfr. [[municipium-si-legge-dalla-sitemap]].
- **openpa**: uffici `/Amministrazione/Uffici`, aree `/Argomenti`, AT `/Amministrazione-Trasparente`; logo su CDN vendor (opencity).
- **comunibootstrapitalia**: verificare se riducibile al connettore WP/AgID **con prova**, non per assunzione.

---
_Connettori-servizio verificati in `treasureiq/catalog/service_connectors/` + `catalog/service_registry.py`. Fotografia piattaforme da `portale_snapshot` (query in §1)._
