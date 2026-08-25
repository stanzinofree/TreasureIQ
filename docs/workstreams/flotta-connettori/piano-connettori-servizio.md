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
