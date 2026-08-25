# Ramo 3 — Connettore servizi WordPress/AgID (nota di consolidamento)

Stato: verificato su endpoint live reali (campione 20 comuni, 2026-08) e
congelato in fixture net-free. Nessuna modifica al resolver comune né
all'infra baseline (commit `1e780e5`).

## Superficie interrogata

- Endpoint: `{sito}/wp-json/wp/v2/{rest_base}` con `rest_base` dalla mappa
  (`mappa.servizi.rest_base`, in pratica sempre `servizi`; override per-comune
  onorato).
- Il CPT reale è `servizio` (singolare) — è lui a esporre `rest_base=servizi`
  (plurale). Verifica in `/wp-json/wp/v2/types`, chiave `servizio`, non
  `servizi` (fixture reale: `arona_types.json`).

## Numero e forma delle richieste

**1 GET REST per ServiceKey**, forma congelata:

```
GET {sito}/wp-json/wp/v2/servizi?search=<termine>&per_page=20&_fields=id,title,link
```

- `<termine>` = `SERVICE_SEARCH_TERM[service_key]`
  (`api/treasureiq/catalog/service_contracts.py`), un solo termine canonico.
- Redirect seguiti a mano con host ricontrollato a ogni hop (www↔apex della
  stessa PA passa, off-host termina il fetch). Nessun login, nessun cookie.
- Se il candidato confermato esiste: +1 GET della sua pagina servizio (solo
  per l'evidenza delle opzioni di accesso; una pagina illeggibile degrada a
  sola opzione INFORMATION, mai a un errore).

## Candidati, regola di conferma, esiti

I candidati sono gli item della risposta (`id`, `title.rendered`, `link`).
Ogni titolo viene ri-passato al riconoscitore condiviso
(`riconosci_service_key`); un candidato è **confermato** solo se il titolo
riconosce esattamente la chiave richiesta.

| Esito | Quando | Prova (fixture reale) |
|---|---|---|
| FULFILLED | esattamente 1 candidato confermato, link su host ufficiale | `arona_carta_identita.json` — n=1 «Rilascio carta d'identità elettronica (CIE)», id 1084 |
| NOT_FOUND (vuoto onesto) | `[]` genuino dall'endpoint | `saintmarcel_carta_empty.json` |
| NOT_FOUND (non confermante) | n=1 ma il titolo non conferma la chiave — mai il «più vicino» | `saintmarcel_statocivile_single.json` — «Certificati anagrafici» per stato civile |
| NOT_FOUND (multi rumoroso) | >1 candidati, 0 o ≥2 confermati | `arona_residenza_multi.json` — 3 titoli, nessuno conferma «cambio di residenza» |

Identità: `service_id = {source_id}:wp:{id}` — mai il titolo. 0 e >1
confermati restano SEMPRE miss onesto (Guard 2 del resolver a monte,
`retrieve` del connettore a valle).

## Leve scartate (con prova)

- **Tassonomia REST del CPT servizi: NON esiste.** Live:
  `/wp/v2/types/servizi` → `rest_base`/`taxonomies` null;
  `/wp/v2/categoria-servizio|argomenti|tipologia-servizio` → 404
  `rest_no_route`. Nei types la tassonomia `categorie_servizio` è
  *dichiarata* sul CPT ma non è instradata in REST. Resta solo il full-text
  `?search=`.
- **Multi-term bounded: respinto.** Aumenta ambiguità e traffico e viola il
  determinismo single-fetch; la conferma via riconoscitore rende un solo
  termine sufficiente. Nessuna fixture ha mostrato un caso in cui un secondo
  termine avrebbe cambiato l'esito in modo onesto.

## Due dialetti REST dietro lo stesso tema (finding critico)

Il tema `design-comuni-wordpress-theme` è identico su entrambi: **il nome
del tema NON basta a separare i dialetti** — serve la forma dell'item REST.

- **Dialetto A (standard WP REST)** — il connettore attuale funziona.
  Item: `{"id":…, "title":{"rendered":…}, "link":…}`; `?search=` e
  `_fields=id,title,link` funzionano. Comuni campione: 003008 Arona,
  003084 Lesa, 003095 Meina, 004009 Bagnolo, 006009 Arquata, 007060
  Saint-Marcel, 012085 Jerago, 001028 Borgaro (flaky ma A).
- **Dialetto B (controller REST custom)** — il connettore attuale produce
  **FALSO VUOTO**. Item: `{"ID":1387, "post_title":"Calcolo IMU online",
  "post_type":"servizio", "stato":"true", "descrizione_breve":…,
  "a_chi_e_rivolto":…, "come_fare":…}` — chiavi maiuscole
  `ID`/`post_title`, campi AgID diretti, NIENTE `link`/`title.rendered`.
  `?search=` ritorna non-JSON; `_fields=id,title,link` svuota ogni item
  (`[[],[],…]`) → 0 candidati. Comuni campione: 023002 Albaredo d'Adige,
  024002 Albettone, 025004 Arsiè. Il loro `servizi.totale=0` in mappa è un
  falso vuoto contato con la forma REST sbagliata, non assenza di servizi.
  Fixture raw: `albaredo_dialettoB_raw.json` (~46KB).
- Comportamento odierno asserito nel test
  `test_fixture_albaredo_dialetto_b_reads_as_false_empty`: NOT_FOUND con 0
  candidati — un difetto di **classificazione**, non un vuoto reale.
- **Follow-up (sessione connettore separata, un connettore per volta):**
  connettore dialetto-B dedicato che legga la forma
  `ID`/`post_title`/`descrizione_breve`/`a_chi_e_rivolto`/`come_fare`
  (niente parser «più permissivo» nel connettore A: 0/≥2 restano miss
  onesto). Da correggere anche il conteggio `servizi.totale` in mappa per i
  comuni B.

## Normalizzazione titoli — finding multi-comune `carta d'identità` (24 ago)

Il campione multi-comune per `carta d'identità` ha rivelato un bug di conferma
**a monte** della disambiguazione: i titoli WP arrivano come **HTML**
(`title.rendered`) e il riconoscitore condiviso non li normalizzava.

- Live su 6 comuni WP-ricchi: 003008 Arona confermava, ma **solo** perché il
  titolo porta il token `(CIE)` che scatta sul marker whole-word `cie`. Il
  percorso substring `carta d'identità` **falliva** su tutti gli altri:
  - 001028 Borgaro: `Carta d&#8217;identità elettronica (C.I.E)` — entity
    apostrofo **e** `C.I.E` puntato (nessun token `CIE`) → **falso NOT_FOUND**.
  - 003084 Lesa / 003095 Meina: `Essere Cittadino &#8211; Carta d&#8217;Identità`
    — entity, nessun token CIE → **falso NOT_FOUND**.
  - 004009 Bagnolo / 006009 Arquata: `n=0` → vuoto genuino.
- Due cause nel matcher condiviso: (a) entity HTML non decodificate
  (`&#8217;`, `&#39;`, `&#8211;`); (b) anche decodificato, l'apostrofo
  tipografico `’` (U+2019) ≠ `'` ASCII dei marker.
- **Fix (cross-family, `chat/service_key.py`):** un chokepoint unico
  `_normalizza` = `html.unescape` + fold apostrofi (`’‘ʼ\`` → `'`) + casefold,
  applicato in `_keys_in`. Nessun connettore toccato. ComWeb faceva già
  `unescape` nel proprio parser (`comweb_service.py:152`), quindi era immune al
  caso `&#39;`; ora è coperto anche il caso `&#8217;` in modo uniforme. Il fold
  è puramente canonicalizzante: non aggiunge marker, non può creare falsi
  positivi; idempotente su testo già pulito.
- **Effetto:** Borgaro/Lesa/Meina ora **FULFILLED** (substring conferma). La
  disambiguazione CIE-vs-minori resta **NOT_FOUND onesto** su ≥2 schede
  confermate (regola immutata; provata su ComWeb Agliè 2-card e su WP
  `arona_residenza_multi`). Nessun comune del campione WP ha ≥2 schede carta,
  quindi il multi-card carta è coperto dal caso ComWeb.
- Fixture reali net-free aggiunte: `borgaro_carta_identita.json`,
  `lesa_carta_identita.json` (byte live, entity incluse). Golden nel
  recogniser: `test_riconosci_service_key_golden` (forme entity/tipografiche) +
  `test_normalizzazione_idempotente_e_senza_falsi_positivi`.
- **Residuo cosmetico (follow-up, non bloccante):** il connettore WP salva
  `ServiceReference.title` dal `rendered` grezzo (entity), quindi il display
  resta `Carta d&#8217;identità` finché il connettore non fa a sua volta
  `unescape` sul titolo memorizzato. La **risoluzione** è corretta; è solo
  qualità di visualizzazione, separata da questa slice.

## Fingerprint (plugin recognition `wordpress_agid_base` 1.1.0, `wordpress-base-v2`)

Marcatori, tutti osservati in fixture reali — nessuno inventato:

| Chiave | Segnali (tutti richiesti) | Fonte |
|---|---|---|
| `generator` / `link_wp_api` / `asset` | ereditati dal classificatore legacy (parità bridge invariata) | home HTML |
| `cpt_servizi` | `"slug":"servizio"` **+** `"rest_base":"servizi"` | `arona_types.json` |
| `rest_item_standard` (dialetto A) | `"id":` **+** `"title":{"rendered"` | `arona_carta_identita.json` |
| `rest_item_custom` (dialetto B) | `"ID":` **+** `"post_title"` **+** `"post_type":"servizio"` | `albaredo_dialettoB_raw.json` |

L'identità resta `wordpress_generico`: i marcatori arricchiscono il
fingerprint (e separano i dialetti), non promuovono un platform id più
specifico — nelle fixture non c'è alcun marcatore di tema (nessuna stringa
«design comuni»/«bootstrap italia» nel payload types): *da verificare con
altra prova live* prima di promuovere un'identità dedicata.

> **Ambito dei marcatori dialetto.** `rest_item_standard` e `rest_item_custom`
> sono segnali osservabili dal **probe REST** (payload della collezione
> `/wp/v2/servizi`). NON sono marcatori utilizzabili dal recognition plugin
> sulla **home HTML** — in pipeline reale il classificatore riceve l'HTML della
> home, non il JSON REST, quindi questi due segnali non scattano lì e **non
> influenzano il routing** finché non viene implementato il connettore-B / probe
> dedicato. Nei test scattano perché ricevono direttamente la fixture JSON: sono
> evidenza/capability registrata, non routing attivo. Il `cpt_servizi` ha la
> stessa natura di probe (payload `/types`).

## Cache e metriche

- Cache-first nel resolver (`resolve_service_with_meta`): hit fresco → nessuna
  rete (`from_cache=True`); miss → connettore, write-back SOLO su FULFILLED
  con esattamente 1 reference; il timestamp persistito è lo stesso
  `retrieved_at` dell'envelope (mai il momento della scrittura).
- Run reale sul campione 20: `da_cache=14` — ogni comune ricco ha ≥1 chiave
  risolta e cachata; Arona carta_identita risolse live (n=1 confermato).
- Lo 0-live dell'ultimo run ha 3 cause oneste (non bug): timeout di server
  piccoli, `[]` genuino su termini multi-parola, conferma che rigetta il
  singolo candidato non conforme. Il 301 www→apex è gestito dagli hop
  manuali del fetch guardato.

## Test net-free aggiunti

- `api/tests/test_wordpress_agid_service_connector.py` — 6 test
  fixture-driven: i byte reali passano da `httpx.MockTransport` →
  `HttpxServiceFetcher` → connettore; asserita anche la forma esatta della
  richiesta (url, `search`/`per_page`/`_fields`) e il single-fetch.
- `api/tests/test_plugin_wordpress_agid_recognition.py` — 4 test: marcatore
  CPT sul payload types reale, doppio-segnale obbligatorio, dialetti A/B
  separati per forma item (fingerprint distinti), ancora `post_type
  servizio` obbligatoria per il dialetto B.
