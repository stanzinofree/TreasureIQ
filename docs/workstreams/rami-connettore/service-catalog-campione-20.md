# service_catalog — campione da 20 comuni (primo run reale)

Campione **pinnato** per il primo run reale (con rete) dello sweep
`service_catalog`, deciso dopo il dry-run nazionale corretto. Lo scopo è
misurare l'hit-rate di **risoluzione** `ServiceKey → ServiceReference` e il
comportamento sui modi di fallimento (vuoto onesto, miss) prima di qualunque
fan-out nazionale.

## Fotografia nazionale (dry-run, net-free)

5464 comuni censiti → **1626 pianificati** (risolvibili), 2448 non supportati
(municipium/peopleweb/egov/openweb/openpa: hanno registro ma nessun connettore
servizi), 1390 senza piattaforma nota (mai scansionati). Piattaforme supportate:
`wordpress_agid` 1126, `comweb` 500.

## Strategia: stratificato per superficie servizi

Un campione random sovrappesa lo strato "ricco" e non testa i fallimenti.
La varianza che conta è la **superficie servizi** che il connettore sonda
(`servizi.esposto` / `servizi.totale` nella mappa-connettore):

- **comweb** — 498/500 supportati **senza mappa-connettore**: la risoluzione
  dipende interamente dalla discovery live del connettore, a freddo. Strato a
  massima incertezza → 6 comuni su 6 province distinte.
- **wordpress_agid** — quattro strati di superficie, coperti tutti:

| Strato | Superficie | Popolazione | Campione | Esito atteso |
|---|---|---:|---:|---|
| ricco | `esposto` + tot ≥10 | 624 | 6 | hit |
| vuoto | `esposto` + tot =0 | 370 | 4 | vuoto onesto (CPT esiste, 0 item) |
| no-surface | `esposto=False` | 111 | 2 | miss |
| sottile | `esposto` + tot 1–9 | 21 | 2 | edge |
| — comweb | (nessuna mappa) | 500 | 6 | discovery live |

## Regola di selezione (riproducibile)

Comuni ordinati per codice ISTAT; per ogni strato si prendono i primi N. Per
`comweb` e `wp_agid tot=0` si applica *spread per provincia* (primo ISTAT per
prefisso-provincia distinto, poi riempimento) per non concentrare lo strato a
massima incertezza su un solo hosting. Rigenerabile dai file
`data-live/registro/*.json` + `data-live/mappa-connettore/*.json`.

## I 20 comuni

| Strato | ISTAT | Comune | servizi_tot |
|---|---|---|---:|
| comweb | 001001 | Agliè | — |
| comweb | 002007 | Asigliano Vercellese | — |
| comweb | 003001 | Agrate Conturbia | — |
| comweb | 004005 | Alto | — |
| comweb | 006002 | Albera Ligure | — |
| comweb | 007002 | Antey-Saint-André | — |
| wp_agid ricco | 001028 | Borgaro Torinese | 60 |
| wp_agid ricco | 003008 | Arona | 317 |
| wp_agid ricco | 003084 | Lesa | 37 |
| wp_agid ricco | 003095 | Meina | 37 |
| wp_agid ricco | 004009 | Bagnolo Piemonte | 27 |
| wp_agid ricco | 006009 | Arquata Scrivia | 23 |
| wp_agid vuoto | 020060 | Schivenoglia | 0 |
| wp_agid vuoto | 023002 | Albaredo d'Adige | 0 |
| wp_agid vuoto | 024002 | Albettone | 0 |
| wp_agid vuoto | 025004 | Arsiè | 0 |
| wp_agid no-surface | 004059 | Cavallermaggiore | esposto=False |
| wp_agid no-surface | 004203 | Saluzzo | esposto=False |
| wp_agid sottile | 007060 | Saint-Marcel | 9 |
| wp_agid sottile | 012085 | Jerago con Orago | 7 |

## Lista ISTAT (per Step 2)

```
001001 002007 003001 004005 006002 007002
001028 003008 003084 003095 004009 006009
020060 023002 024002 025004
004059 004203
007060 012085
```

## Gate

Il run reale su questo campione **è** un'esecuzione con rete: richiede lo Step 2
(esecuzione reale + metriche per-run atomiche dopo ogni batch) e resta dietro il
gate esplicito prima di qualunque fan-out nazionale. Oggi `service_catalog`
senza `--dry-run` ritorna `EXIT_SERVICE_REAL_NOT_READY` (uscita 3).
