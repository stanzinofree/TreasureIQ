# Workstream — Rami connettore

Analisi pulita dei **rami-capability** che un cittadino può chiedere, per
ricondurre i 6 connettori di piattaforma a un **contratto comune** (motore
unico v1) e completare il censimento ramo per ramo.

Base: `analysis/rami-connettore` (da `refactor/source-engine`).

## I rami

Ortogonali al dispatch interno (`QuestionKind`/`Topic` in `_componi_risposta`):
questi sono *cosa* si chiede al portale, non *come* si instrada.

| # | Ramo | Surface · capability | Stato contratto | Doc |
|---|------|----------------------|-----------------|-----|
| 1 | **Ufficio** — orari, contatti, responsabili | ORDINARY_DATA · `offices`+`contacts` | parziale | [ramo-1-ufficio.md](ramo-1-ufficio.md) |
| 2 | **Bandi** — aperti + chiusi <90gg | TRANSPARENCY · `notices` | da scrivere | ramo-2-bandi.md (todo) |
| 3 | **Modulistica** — moduli servizi (SP) | SERVICE_PORTAL · `service_id` | cablato, 0 caller | ramo-3-modulistica.md (todo) |
| 4 | **Sconosciuto** — ripeti / URP | — nessun connettore — | n/a | — |

## Il ciclo per ogni ramo

```
1. brainstorm      → cosa possiamo tirar fuori da questo ramo
2. contratto comune → come il connettore universale ci si riconduce
3. porting          → i connettori esistenti di quel ramo alla versione nuova
4. censimento       → completare la copertura
→ ramo successivo, fino a esaurirli
```

## Vocabolario universale (contratti v1)

- **Surface** (`catalog/contracts.py`): `SOURCE_IDENTITY` · `ORDINARY_DATA` · `TRANSPARENCY` · `SERVICE_PORTAL`
- **AccessMode**: `DIRECT` (REST tipato) · `MEDIATED` (scrape strutturato) · `INDIRECT` (puntatore, no login) · `UNAVAILABLE`
- **DataRequest**(surface, capability, selection) → **DataBatch**(status, access_mode, records, evidence, freshness)

## Le 7 piattaforme di flotta

`FLOTTA_PLATFORMS`: `municipium` · `comweb` · `peopleweb` · `openweb` · `openpa`
· `egov` · `hgate`. Ciascuna con reader v0 (firma D-09 congelata
`(comune, sonda) -> EsitoConnettore`, mai `None`, mai solleva). In v1 = **14
unità versionate** (Base + Trasparenza per piattaforma), più il **bridge
WordPress** esplicito per 4 platform ID (`wordpress_agid`, `wp_design_comuni`,
`wordpress_generico`, `comunibootstrapitalia`). Il fallback wildcard è
`web_scrape` (`platforms=("*",)`). `hgate` è distinta ma
**colocata nel modulo `egov`** (reader condiviso). Copertura ~69% dei comuni.

**Proiezione unica** `EsitoConnettore → DataBatch` in
`catalog/flotta/_projection.py` + `_base.py` (`FlottaBaseConnettore`): generica,
condivisa da tutta la flotta — NON per-piattaforma, NON in `wordpress_agid`.
