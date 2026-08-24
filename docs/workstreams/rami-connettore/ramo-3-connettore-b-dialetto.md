# Ramo 3 — Connettore-B WP/AgID: il dialetto REST custom (design + evidenza)

Stato: **IMPLEMENTATO** (in-band self-detect). Evidenza da probe live Albaredo
d'Adige (023002) + sniff dei 20 comuni pinnati (`CAMPIONE_SERVICE_CATALOG_20`),
24 ago 2026. Nessun cambio a resolver, sweep, cache, o fingerprint della mappa.

## 1. Il problema (dal vivo)

Alcuni comuni servono lo **stesso** tema Design Comuni/AgID attraverso un
controller REST **custom** che *sovrascrive* `wp/v2/servizi`. Dal vivo (Albaredo):

- le righe hanno chiavi `ID` / `post_title` / `post_name` / `guid` / `post_type`
  + i campi AgID pieni — **non** `id` / `title.rendered` / `link`;
- `search` / `per_page` / `_fields` lato server sono **ignorati**: ogni chiamata
  ritorna il **dump completo** del catalogo (20 voci per Albaredo);
- con `_fields=id,title,link` la risposta è `[[], [], …]` (array vuoti): il parser
  standard legge **0 candidati da un payload che È pieno di servizi** — un *falso
  vuoto*, non un vuoto reale;
- `guid` è un URL assoluto valido fornito dal server
  (`https://…/?post_type=servizio&p=1387`).

## 2. Copertura sul campione (perché conta)

La **misura live** (24 ago, connettore reale guardato sui 20 comuni × 6
ServiceKey, `misura_dialetto_b.py`) classifica per *path effettivamente
percorso* (segnale in-band), non per uno sniff a priori:

| classe | n | comuni |
|---|---|---|
| standard (`id`/`title`/`link`) | 7 | 001028, 003084, 003095, 004009, 006009, 007060, 012085 |
| **dialetto B** (`ID`/`post_title`) | **5** | 003008, 020060 Schivenoglia, 023002 Albaredo, 024002 Albettone, 025004 Arsiè |
| non-WP / non-esposto | 8 | ComWeb / altre famiglie / 401 (NOT_SUPPORTED, 0 fetch) |

**003008 era stato pre-classificato «standard»** dallo sniff iniziale, ma dal
vivo serve dialetto B: l'in-band l'ha riconosciuto **da solo**, senza alcuna
pre-etichetta. I 5 dialetto-B davano **quasi solo miss** (il parser standard
scartava tutto): una fetta reale dei 94 miss.

### 2.1 Perché il fingerprint persistito avrebbe fallito (evidenza 003008)

`AssetServizi.rest_item_custom` sarebbe stato scritto in scansione dallo stesso
sniff che ha **mis-classificato 003008 come standard**: il connettore avrebbe
letto un flag «standard», imboccato il path standard, letto 0 da un payload
pieno → **miss silenzioso** su un comune servibile. Il fingerprint eredita
l'errore del momento in cui è stato misurato; l'in-band legge il segnale dalla
risposta HTTP corrente e non può sbagliare classe. Il quinto dialetto è la prova
diretta: **non era prevedibile dal fingerprint, l'auto-detect l'ha preso.**

### 2.2 Esito misura (parità standard, recupero dialetto-B)

31 FULFILLED sul campione: **15 standard** (1 REST/chiave, byte-identico al
pre-dialetto) + **16 dialetto-B** (2 REST/chiave, prima tutti miss). 48
NOT_SUPPORTED sui non-WP/non-esposti (0 fetch). I miss residui sono tutti
0/≥2 onesti (mai il più vicino). Nessuna scrittura su `storico.db`.

## 3. Decisione: in-band self-detect (non il fingerprint `rest_item_custom`)

La slice proponeva un campo di fingerprint `AssetServizi.rest_item_custom` scritto
in scansione e letto dal connettore. **Scartato** a favore del rilevamento in-band:

- la risposta slim `[[], …]` **è già** il segnale inequivocabile del dialetto B
  (lista **non vuota** ma con **0 candidati standard**): non serve un flag
  persistito per instradare;
- persistere il flag richiederebbe un **ri-sweep** dei comuni per popolarlo — e la
  slice vieta esplicitamente di toccare sweep/scan;
- l'in-band è **contenuto**: tocca solo le due discovery WP + un parser condiviso;
  zero cambi a protocollo `ServiceFetcher`, ComWeb, `DiscoveryTarget`, base.

### Meccanica (`raccogli_candidati_wp`, in `esecutore_fetcher.py`)

1. ricerca slim standard (`_fields=id,title,link`) — **byte-identica** a prima;
2. se ≥1 candidato standard → autoritativa, **nessuna** seconda richiesta;
3. se lista **non vuota** ma **0** standard → dialetto B: **una** GET in più
   **senza** `_fields` (`rileggi_grezzo`), righe lette con la forma B
   (`ID`/`post_title`/`guid`);
4. `[]` **genuino** → miss onesto a **una** richiesta (nessun fallback).

Il layer di conferma (host guard + recogniser condiviso, **0/≥2 → NOT_FOUND**) è
**immutato**: il dialetto B cambia solo *come* le righe si scaricano e si
modellano, mai *come* si giudica un match. `service_id` = `{istat}:wp:{ID}`,
`source_url` = `guid` (mai il titolo, mai un URL inventato).

Condiviso da entrambi i path WP: `HttpxServiceFetcher` (test/confine HTTP) e
`_WpDiscovery` (runtime guardato). Un solo parser custom, nessun drift.

## 4. Costo

- comuni **standard**: **1** richiesta, invariata (candidati trovati → no refetch);
- comuni **dialetto B**: **2** richieste (slim vuota + recupero senza `_fields`);
- `[]` reale: **1** richiesta.

Il refetch senza `_fields` scarica il dump pieno (~45 KB per Albaredo, < cap REST
512 KB). La ricerca resta full-dump lato server: la conferma per-titolo filtra.

Nota misurata: sui dialetto-B la lettura della pagina servizio parte dal `guid`
(`?post_type=servizio&p=ID`), che il server **redirige** al permalink → 1 hop di
redirect in più sul fetch HTML delle opzioni (seguito dall'host guard, non una
seconda query logica). Sul path standard il `link` è già il permalink: nessun hop.

## 5. Esiti onesti provati sul dump reale Albaredo (golden)

Un solo fixture (`albaredo_dialettoB_raw.json`, 20 voci reali) copre tutti e
quattro gli esiti (transport param-aware: `[[], …]` sulla slim, dump sul grezzo):

| ServiceKey | voci confermanti | esito |
|---|---|---|
| TRIBUTI_IMU | 1 — «Calcolo IMU online» (ID 1387) | **FULFILLED** |
| CARTA_IDENTITA | 1 — «Rilascio Carta d'Identità Elettronica» (289) | FULFILLED |
| TRIBUTI_TARI | 0 | **NOT_FOUND** (vuoto onesto dopo recupero) |
| CAMBIO_RESIDENZA | 2 (1280, 290) on-host | **NOT_FOUND** (≥2, mai il più vicino) |

Più il guard: `[]` genuino (Saint-Marcel) → **1** richiesta, nessun refetch.

## 6. Follow-up aperti

- **Fast-path fingerprint (rimandato):** se la misura mostra che il refetch pesa,
  `AssetServizi.rest_item_custom` (evidence-gated in scan) potrebbe risparmiare la
  prima richiesta slim sprecata sui dialetto-B noti. Oggi non necessario per
  correttezza; da valutare **dopo** la misura sul campione.
- **Titolo entity-encoded** (`post_title` grezzo): stesso follow-up del path
  standard — la conferma è robusta (recogniser `_normalizza`), il *display* è un
  fix solo-connettore separato. Vedi memoria `wp-title-entity-encoded-followup`.
