# Promozione IMIS -> catalogo (tributi_imu) — 2026-09-02

Promozione **data-only** dei servizi IMIS (Imposta Immobiliare Semplice, l'IMU trentina) confermati **exactly-one** sui comuni OpenPA/OpenCity del Trentino. Base: main (#76 risoluzione IMIS + #77 disambiguazione). Nessuna modifica a codice, cache, DB o connettori.

## Sintesi

| Esito | N |
|---|---|
| Promossi (chiave tributi_imu aggiunta) | 86 |
| — con azione autenticata regionale (delegated_host=IMIS_TRENTINO) | 84 |
| — solo informativi (host comunale) | 2 |
| Esclusi (host authenticated_online fuori allowlist) | 4 |
| Skip-esistenti (tributi_imu gia in catalogo, invariati) | 5 |
| **Totale candidati FULFILLED** | 95 |

## Policy di validazione (allowlist puntuale)

- source_url + opzione INFORMATION: host ufficiale del comune;
- authenticated_online: SOLO HTTPS su consulenza.comunitrentini.tn.it (portale IMIS regionale del consorzio), registrato come delegated_host=IMIS_TRENTINO;
- download: SOLO host ufficiale;
- rifiuto di altri host, porte non standard, userinfo;
- serializzazione via ServiceReference.model_dump(mode=json); discovered_at normalizzato al batch (T00:00:00Z), nessun campo costruito a mano.

## Esclusi (4) — host IMIS di vendor diverso, fuori allowlist corrente

Servizi IMIS reali ma con azione autenticata delegata a portali diversi dal regionale. Restano risolvibili live; ampliabili solo con recon separata e verifica host/vendor.

| ISTAT | host authenticated_online |
|---|---|
| 022097 | https://imisimer.giscoservice.it/ |
| 022115 | https://imismezzano.giscoservice.it/ |
| 022235 | https://imisaltavalle.giscoservice.it/ |
| 022236 | https://dgegovpa.it/Vigolana/login |

## Casi solo informativi (2) — promossi, nessuna azione autenticata

- **022142** — service_id 022142:openpa:414
- **022161** — service_id 022161:openpa:4316

## Skip-esistenti (5) — invariati

- 022034 — 022034:openpa:621
- 022137 — 022137:openpa:597
- 022138 — 022138:openpa:931
- 022168 — 022168:openpa:845
- 022190 — 022190:openpa:529
